"""Real media tests, not mocked claims of a successful video render."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import creative

class CreativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rootpatch = patch.object(creative, 'ROOT', self.root)
        self.rootpatch.start()
        self.addCleanup(self.rootpatch.stop)

    def test_logo_is_real_and_escaped(self):
        result = creative.logo_design({'brand': 'ESN & Hosting', 'symbol': 'shield'})
        contents = (self.root / 'exports' / result['svg']).read_text()
        self.assertIn('ESN &amp; Hosting', contents)
        self.assertIn('<svg ', contents)
        self.assertNotIn('<script>', contents)
        if result['png']:
            self.assertGreater((self.root / 'exports' / result['png']).stat().st_size, 100)

    def test_invalid_paths_are_rejected(self):
        input_dir = self.root / 'inputs'
        input_dir.mkdir()
        outside = self.root / 'not-input.mp4'
        outside.write_bytes(b'outside')
        (input_dir / 'shortcut.mp4').symlink_to(outside)
        for raw in ('../not-input.mp4', '/etc/passwd', 'https://example.com/a.mp4', 'shortcut.mp4', 'not-input.mp4'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                creative.input_asset(raw, creative.VIDEO_EXT)

    def test_edit_spec_rejects_shell_injection(self):
        with self.assertRaises(ValueError):
            creative.validate_video_spec({'clips': [{'file': '/etc/passwd;rm -rf /', 'duration': 3}]})

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg not installed in CI')
    def test_render_real_video_with_title(self):
        p = creative.workspace() / 'inputs' / 'test.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i','color=c=blue:s=320x240:d=1:r=24','-c:v','libx264','-threads','1',str(p)],timeout=30,check=True)
        with patch.dict(creative.SIZES, {'short':(180,320)}):
            result = creative.render_video({'clips':[{'file':'test.mp4','start':0,'duration':.6,'title':'ESN EDIT'}], 'format':'short', 'fps':24})
        movie = self.root / 'exports' / result['filename']
        self.assertGreater(movie.stat().st_size, 1500)
        metadata = creative.probe(movie)
        self.assertGreater(metadata['duration'],.45)
        self.assertTrue((self.root/'exports'/result['handoff']['editor_zip']).exists())
        script = (self.root/'exports'/result['handoff']['after_effects_script']).read_text()
        self.assertIn('app.beginUndoGroup',script)
        self.assertIn('ESN EDIT',script)

    def test_unknown_logo_style(self):
        with self.assertRaises(ValueError):
            creative.logo_design({'brand': 'ESN', 'symbol': '<script>'})

if __name__ == '__main__':
    unittest.main()
