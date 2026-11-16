import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import archive


class PackageChecks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "example"
        self.root.mkdir()
        (self.root / "golden.txt").write_bytes(b"hello\nworld")
        self.manifest = {"schema":1,"model_id":"example","files":archive.package_entries(self.root)}
        archive.atomic_write(self.root/"manifest.json",archive.encoded(self.manifest))

    def test_byte_level_tamper(self):
        (self.root/"golden.txt").write_bytes(b"hello\r\nworld")
        with self.assertRaises(ValueError):
            archive.local(self.root,"example")

    def test_paths_and_duplicate_entries(self):
        for path in ("../file","/absolute","C:/device","dir/./x","dir//x","."):
            with self.subTest(path=path), self.assertRaises(ValueError):
                archive.relative(path)
        self.manifest["files"].append(self.manifest["files"][0])
        with self.assertRaises(ValueError):
            archive.check_manifest(self.manifest,"example")

    def test_different_greedy_output_fails(self):
        with patch.object(archive,"command"), patch.object(archive,"golden",return_value=b"changed"):
            with self.assertRaisesRegex(ValueError,"Greedy output differs"):
                archive.regress(self.root,"example")

    def test_failed_copy_has_no_receipt(self):
        mirrors=archive.read_mirrors(Path(__file__).with_name("mirrors.example.json"))
        with patch.object(archive,"command"), patch.object(archive,"remote_fingerprint",side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                archive.replicate(self.root,"example",mirrors,upload=True)
        self.assertFalse((self.root/"receipt.json").exists())
