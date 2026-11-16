"""CPU inference. The archive's golden runner imports this same implementation."""
import argparse
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from common import Generation


class PromptTooLong(ValueError):
    pass


class Transformers:
    def __init__(self, folder):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        path = folder / "converted/safetensors"
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        self.model = AutoModelForCausalLM.from_pretrained(
            path, local_files_only=True, trust_remote_code=False, use_safetensors=True,
            torch_dtype=torch.float32).eval()

    def events(self, req, cancel):
        from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer
        ids = self.tokenizer(req.prompt, return_tensors="pt", add_special_tokens=False).input_ids
        context = getattr(self.model.config, "max_position_embeddings", self.tokenizer.model_max_length)
        prompt_count = ids.shape[1]
        if not prompt_count or prompt_count + req.max_tokens > context:
            raise PromptTooLong(f"Prompt and requested continuation must fit {context} tokens")

        class Cancelled(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return cancel.is_set()

        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True,
                                        clean_up_tokenization_spaces=False, timeout=0.25)
        result = {}
        def generate():
            try:
                self.torch.manual_seed(req.seed if req.seed is not None else secrets.randbelow(2**31))
                sampling = (dict(temperature=req.temperature, top_p=req.top_p, top_k=0)
                            if req.temperature else {})
                with self.torch.inference_mode():
                    output = self.model.generate(
                        ids, attention_mask=self.torch.ones_like(ids), streamer=streamer,
                        max_new_tokens=req.max_tokens, do_sample=bool(req.temperature),
                        repetition_penalty=1.0, num_beams=1, stopping_criteria=StoppingCriteriaList([Cancelled()]),
                        pad_token_id=self.tokenizer.eos_token_id, **sampling)
                count = output.shape[1] - prompt_count
                result.update(finish_reason="length" if count == req.max_tokens else "stop",
                              prompt_tokens=prompt_count, completion_tokens=count)
            except BaseException as exc:
                result["error"] = exc
                streamer.on_finalized_text("", stream_end=True)

        thread = threading.Thread(target=generate, daemon=True)
        thread.start()
        try:
            while True:
                try:
                    part = next(streamer)
                except queue.Empty:
                    continue
                except StopIteration:
                    break
                if part:
                    yield {"text": part}
        finally:
            # The streamer may end before generate returns. Cancellation after that final token is harmless.
            cancel.set()
            thread.join()
        if "error" in result:
            raise RuntimeError("Generation failed") from result["error"]
        yield result

    def close(self):
        self.model = self.tokenizer = None


class Gguf:
    def __init__(self, folder):
        port = int(os.getenv("SANCTUARY_LLAMA_PORT","8082"))
        self.url = f"http://127.0.0.1:{port}"
        self.process = subprocess.Popen([
            os.getenv("SANCTUARY_LLAMA_BIN","llama-server"), "-m", str(folder / "converted/model.gguf"),
            "--host","127.0.0.1","--port",str(port),"-ngl","0","-c","0","--parallel","1",
            "--no-context-shift","--log-disable"],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.client = httpx.Client(timeout=httpx.Timeout(300,connect=3))
        try:
            for _ in range(600):
                if self.process.poll() is not None:
                    raise RuntimeError("llama-server exited during startup")
                try:
                    if self.client.get(self.url+"/health").is_success:
                        return
                except httpx.RequestError:
                    pass
                time.sleep(0.5)
            raise RuntimeError("llama-server startup timed out")
        except BaseException:
            self.close()
            raise

    def events(self, req, cancel):
        payload = dict(prompt=req.prompt, n_predict=req.max_tokens, temperature=req.temperature,
                       top_p=req.top_p, seed=req.seed, top_k=0, min_p=0,
                       repeat_penalty=1.0, cache_prompt=False, stream=True)
        if req.seed is None:
            payload["seed"] = secrets.randbelow(2**31)
        with self.client.stream("POST",self.url+"/completion",json=payload) as response:
            if response.status_code in (400,413):
                raise PromptTooLong("Prompt exceeds the model's context")
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel.is_set():
                    return
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("error"):
                    raise RuntimeError("llama-server reported an inference error")
                if event.get("truncated"):
                    raise PromptTooLong("Prompt exceeds the model's context")
                if event.get("content"):
                    yield {"text":event["content"]}
                if event.get("stop"):
                    yield dict(finish_reason="length" if event.get("stop_type")=="limit" else "stop",
                               prompt_tokens=event["tokens_evaluated"],completion_tokens=event["tokens_predicted"])
                    return
        raise RuntimeError("Incomplete llama-server stream")

    def close(self):
        self.client.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def engine_name(folder):
    return os.environ.get("SANCTUARY_ENGINE") or ("gguf" if (folder/"converted/model.gguf").exists() else "transformers")


def load_engine(folder):
    return {"gguf":Gguf,"transformers":Transformers}[engine_name(folder)](folder)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the deterministic archival baseline")
    parser.add_argument("--package",type=Path,required=True)
    parser.add_argument("--prompt-file",type=Path,required=True)
    parser.add_argument("--max-tokens",type=int,default=32)
    args = parser.parse_args()
    req = Generation(prompt=args.prompt_file.read_bytes().decode("utf-8"),max_tokens=args.max_tokens,
                     temperature=0,top_p=1,seed=0)
    engine = load_engine(args.package)
    try:
        for event in engine.events(req,threading.Event()):
            if "text" in event:
                sys.stdout.buffer.write(event["text"].encode("utf-8"))
    finally:
        engine.close()
