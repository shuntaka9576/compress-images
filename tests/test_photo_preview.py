from PIL import Image
import pytest
from photo_preview import load_photo


def test_preview_applies_orientation_without_modifying_source(tmp_path):
    source = tmp_path / "portrait.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (120, 60), "orange").save(source, exif=exif)
    original = source.read_bytes()
    preview = load_photo(source, (80, 80))
    assert preview.size == (40, 80)
    assert source.read_bytes() == original
    source.unlink()  # Decoder released its file handle.
    assert preview.getpixel((0, 0))[0] > 240


def test_unreadable_preview_reports_error(tmp_path):
    source = tmp_path / "broken.jpg"
    source.write_bytes(b"not a photo")
    with pytest.raises(OSError):
        load_photo(source, (70, 54))


@pytest.mark.parametrize('orientation', range(1, 9))
def test_reduced_jpeg_decode_keeps_exif_orientation(tmp_path, orientation):
    from PIL import ImageOps, ImageDraw
    source = tmp_path / 'oriented.jpg'
    im = Image.new('RGB', (1600, 1200), 'red')
    ImageDraw.Draw(im).rectangle((800, 0, 1599, 599), fill='blue')
    ImageDraw.Draw(im).rectangle((0, 600, 799, 1199), fill='green')
    exif = Image.Exif(); exif[274] = orientation
    im.save(source, quality=95, exif=exif)
    actual = load_photo(source, (70, 54))
    with Image.open(source) as original:
        expected = ImageOps.exif_transpose(original)
        expected.thumbnail((70, 54))
        # Compare interior colours; reduction rounding can differ by one pixel.
        for x, y in ((.2, .2), (.8, .2), (.2, .8), (.8, .8)):
            a = actual.getpixel((int(actual.width*x), int(actual.height*y)))
            b = expected.getpixel((int(expected.width*x), int(expected.height*y)))
            assert max(abs(i-j) for i,j in zip(a,b)) < 8
