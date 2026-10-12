"""Profile-picture service: normalisation and the identity-provider hook."""

import io

import mongomock
import pytest
from bson import ObjectId
from PIL import Image

from depictio.api.v1.services import avatars


def _image_bytes(size=(400, 200), color=(200, 30, 30), fmt="PNG", **save_kwargs) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format=fmt, **save_kwargs)
    return out.getvalue()


@pytest.fixture()
def store(monkeypatch):
    collection = mongomock.MongoClient()["depictio_test"]["user_avatars"]
    monkeypatch.setattr(avatars, "user_avatars_collection", collection)
    return collection


class TestNormalizeImage:
    def test_crops_to_a_square_and_resizes(self):
        data, content_type, width, height = avatars.normalize_image(_image_bytes((400, 200)))
        assert (width, height) == (avatars.AVATAR_SIZE, avatars.AVATAR_SIZE)
        assert content_type == "image/webp"
        with Image.open(io.BytesIO(data)) as out:
            assert out.size == (avatars.AVATAR_SIZE, avatars.AVATAR_SIZE)
            assert out.format == "WEBP"

    def test_crop_is_centred(self):
        # Left third red, middle third green, right third blue: the centred
        # square of a wide image keeps the middle.
        wide = Image.new("RGB", (300, 100))
        for x in range(300):
            colour = (255, 0, 0) if x < 100 else (0, 255, 0) if x < 200 else (0, 0, 255)
            for y in range(100):
                wide.putpixel((x, y), colour)
        buf = io.BytesIO()
        wide.save(buf, format="PNG")
        data, *_ = avatars.normalize_image(buf.getvalue())
        with Image.open(io.BytesIO(data)) as out:
            r, g, b = out.convert("RGB").getpixel((128, 128))
        assert g > 200 and r < 60 and b < 60

    def test_applies_exif_orientation(self):
        # A 200x100 image tagged "rotate 90": upright it is 100x200, so the
        # square crop is taken from the rotated pixels (left half red).
        img = Image.new("RGB", (200, 100), (0, 0, 255))
        for x in range(100):
            for y in range(100):
                img.putpixel((x, y), (255, 0, 0))
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 degrees clockwise to display
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)
        data, *_ = avatars.normalize_image(buf.getvalue())
        with Image.open(io.BytesIO(data)) as out:
            top = out.convert("RGB").getpixel((128, 20))
            bottom = out.convert("RGB").getpixel((128, 235))
        # Red ends up on top once rotated clockwise.
        assert top[0] > 180 and top[2] < 80
        assert bottom[2] > 180 and bottom[0] < 80

    def test_strips_metadata(self):
        exif = Image.Exif()
        exif[0x010F] = "SecretCamera"
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (1, 2, 3)).save(buf, format="JPEG", exif=exif)
        data, *_ = avatars.normalize_image(buf.getvalue())
        with Image.open(io.BytesIO(data)) as out:
            assert not out.getexif()
        assert b"SecretCamera" not in data

    def test_never_returns_the_input_bytes(self):
        raw = _image_bytes((256, 256))
        data, *_ = avatars.normalize_image(raw)
        assert data != raw

    def test_keeps_transparency(self):
        buf = io.BytesIO()
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(buf, format="PNG")
        data, *_ = avatars.normalize_image(buf.getvalue())
        with Image.open(io.BytesIO(data)) as out:
            assert out.convert("RGBA").getpixel((10, 10))[3] == 0

    @pytest.mark.parametrize(
        "garbage",
        [b"", b"not an image at all", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"%PDF-1.7"],
    )
    def test_rejects_non_images(self, garbage):
        with pytest.raises(avatars.AvatarError):
            avatars.normalize_image(garbage)

    @pytest.mark.parametrize("fmt", ["BMP", "TIFF", "EPS", "ICO"])
    def test_rejects_formats_outside_the_allow_list(self, fmt):
        out = io.BytesIO()
        Image.new("RGB", (32, 32), (10, 20, 30)).save(out, format=fmt)
        with pytest.raises(avatars.AvatarError) as caught:
            avatars.normalize_image(out.getvalue())
        assert caught.value.status == 415

    def test_large_jpeg_is_shrunk_and_keeps_its_orientation(self):
        # Bigger than the working edge, so draft/thumbnail both kick in, tagged
        # "rotate 90": the left half (red) must still end up on top.
        img = Image.new("RGB", (3000, 1500), (0, 0, 255))
        img.paste((255, 0, 0), (0, 0, 1500, 1500))
        exif = Image.Exif()
        exif[0x0112] = 6
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)
        data, *_ = avatars.normalize_image(buf.getvalue())
        with Image.open(io.BytesIO(data)) as out:
            top = out.convert("RGB").getpixel((128, 20))
            bottom = out.convert("RGB").getpixel((128, 235))
        assert top[0] > 180 and top[2] < 80
        assert bottom[2] > 180 and bottom[0] < 80

    def test_rejects_truncated_image(self):
        with pytest.raises(avatars.AvatarError):
            avatars.normalize_image(_image_bytes()[:50])

    def test_rejects_oversize_input(self):
        with pytest.raises(avatars.AvatarTooLarge) as caught:
            avatars.normalize_image(b"\x00" * (avatars.MAX_INPUT_BYTES + 1))
        assert caught.value.status == 413

    def test_rejects_huge_canvas(self, monkeypatch):
        monkeypatch.setattr(avatars, "MAX_INPUT_PIXELS", 100)
        with pytest.raises(avatars.AvatarError) as caught:
            avatars.normalize_image(_image_bytes((64, 64)))
        assert caught.value.status == 413


class TestUploadedAvatar:
    def test_store_get_delete(self, store):
        user_id = ObjectId()
        doc = avatars.set_uploaded_avatar(user_id, _image_bytes())
        assert doc["source"] == "upload" and doc["provider"] is None

        stored = avatars.get_avatar(user_id)
        assert stored is not None
        assert stored["content_type"] == "image/webp"
        assert len(avatars.avatar_bytes(stored)) > 0
        assert avatars.get_avatar_meta(user_id).get("data_b64") is None
        assert avatars.avatar_updated_at_iso(stored) is not None
        assert "+" not in avatars.avatar_updated_at_iso(stored)

        assert avatars.delete_avatar(user_id) is True
        assert avatars.get_avatar(user_id) is None
        assert avatars.delete_avatar(user_id) is False

    def test_bad_upload_stores_nothing(self, store):
        user_id = ObjectId()
        with pytest.raises(avatars.AvatarError):
            avatars.set_uploaded_avatar(user_id, b"nope")
        assert avatars.get_avatar(user_id) is None


@pytest.mark.asyncio
class TestProviderHook:
    URL = "https://lh3.googleusercontent.com/a/photo=s96-c"

    @pytest.fixture()
    def downloads(self, monkeypatch):
        calls = []

        async def fake_download(url):
            calls.append(url)
            return _image_bytes()

        monkeypatch.setattr(avatars, "_download", fake_download)
        return calls

    async def test_stores_a_provider_picture(self, store, downloads):
        user_id = ObjectId()
        assert await avatars.set_provider_avatar(user_id, provider="google", url=self.URL) is True
        doc = avatars.get_avatar(user_id)
        assert doc["source"] == "provider"
        assert doc["provider"] == "google"
        assert doc["provider_url"] == self.URL
        assert downloads == [self.URL]

    async def test_raw_bytes_need_no_download(self, store, downloads):
        user_id = ObjectId()
        assert await avatars.set_provider_avatar(user_id, provider="saml", raw=_image_bytes())
        assert avatars.get_avatar(user_id)["provider"] == "saml"
        assert downloads == []

    async def test_upload_always_wins(self, store, downloads):
        user_id = ObjectId()
        avatars.set_uploaded_avatar(user_id, _image_bytes())
        assert await avatars.set_provider_avatar(user_id, provider="google", url=self.URL) is False
        assert avatars.get_avatar(user_id)["source"] == "upload"
        assert downloads == []

    async def test_unchanged_url_skips_the_download(self, store, downloads):
        user_id = ObjectId()
        await avatars.set_provider_avatar(user_id, provider="google", url=self.URL)
        assert await avatars.set_provider_avatar(user_id, provider="google", url=self.URL) is False
        assert downloads == [self.URL]

    async def test_changed_url_replaces_the_picture(self, store, downloads):
        user_id = ObjectId()
        await avatars.set_provider_avatar(user_id, provider="google", url=self.URL)
        other = self.URL + "2"
        assert await avatars.set_provider_avatar(user_id, provider="google", url=other) is True
        assert avatars.get_avatar(user_id)["provider_url"] == other

    async def test_removed_upload_lets_the_provider_back_in(self, store, downloads):
        user_id = ObjectId()
        avatars.set_uploaded_avatar(user_id, _image_bytes())
        avatars.delete_avatar(user_id)
        assert await avatars.set_provider_avatar(user_id, provider="google", url=self.URL)

    async def test_an_upload_landing_during_the_download_wins(self, store, monkeypatch):
        user_id = ObjectId()

        async def slow_download(url):
            # The user uploads their own picture while the provider's is fetched.
            avatars.set_uploaded_avatar(user_id, _image_bytes(color=(0, 255, 0)))
            return _image_bytes()

        monkeypatch.setattr(avatars, "_download", slow_download)
        assert await avatars.set_provider_avatar(user_id, provider="g", url=self.URL) is False
        doc = avatars.get_avatar(user_id)
        assert doc["source"] == "upload"
        assert doc["provider"] is None

    async def test_network_failure_returns_false(self, store, monkeypatch):
        async def boom(url):
            raise RuntimeError("connection reset")

        monkeypatch.setattr(avatars, "_download", boom)
        user_id = ObjectId()
        assert await avatars.set_provider_avatar(user_id, provider="g", url=self.URL) is False
        assert avatars.get_avatar(user_id) is None

    async def test_garbage_payload_returns_false(self, store, monkeypatch):
        async def junk(url):
            return b"<html>not an image</html>"

        monkeypatch.setattr(avatars, "_download", junk)
        assert await avatars.set_provider_avatar(ObjectId(), provider="g", url=self.URL) is False

    async def test_nothing_to_store(self, store, downloads):
        assert await avatars.set_provider_avatar(ObjectId(), provider="g") is False

    async def test_http_url_is_refused_without_a_request(self, store):
        # The real downloader: plain http fails before any connection is made.
        result = await avatars.set_provider_avatar(
            ObjectId(), provider="g", url="http://example.com/me.png"
        )
        assert result is False
