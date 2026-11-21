import hashlib, os, tempfile, unittest
import data_checksums as dc

class DataChecksumsTests(unittest.TestCase):
    def test_table_and_render(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'Rooms'))
            os.makedirs(os.path.join(d, 'OTHER'))
            big = bytes(range(256)) * 40
            for rel, data in [('bioforge.exe', b'abc'), ('Rooms/a.cam', big), ('INSTALL.OPT', b'x'), ('OTHER/z', b'z')]:
                with open(os.path.join(d, rel), 'wb') as f: f.write(data)
            rows = dc.table(d)
            self.assertEqual(rows, [('BIOFORGE.EXE', 3, hashlib.md5(b'abc').hexdigest()),
                                    ('ROOMS/A.CAM', len(big), hashlib.md5(big[:5000]).hexdigest())])
            self.assertIn('("ROOMS/A.CAM", %d, "%s"),' % rows[1][1:], dc.render(rows))

if __name__ == '__main__': unittest.main()
