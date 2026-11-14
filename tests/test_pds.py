import pytest

from twinworld.pds import read_byte_range


class FakeResponse:
    def __init__(self, status_code=206, content_range="bytes 10-12/100", content=b"abc"):
        self.status_code = status_code
        self.headers = {"Content-Range": content_range}
        self.content = content
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.request = None

    def get(self, url, **kwargs):
        self.request = (url, kwargs)
        return self.response


def test_read_byte_range_sends_and_verifies_exact_inclusive_range():
    response = FakeResponse()
    session = FakeSession(response)

    payload = read_byte_range(
        "https://pds.example/data.img",
        10,
        12,
        timeout=30,
        session=session,
    )

    assert payload == b"abc"
    assert session.request == (
        "https://pds.example/data.img",
        {
            "headers": {"Range": "bytes=10-12"},
            "timeout": 30,
            "stream": True,
        },
    )
    assert response.closed


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(status_code=200), "did not honor"),
        (FakeResponse(content_range="bytes 9-12/100"), "Content-Range"),
        (FakeResponse(content=b"ab"), "length does not match"),
    ],
)
def test_read_byte_range_rejects_unbounded_or_malformed_responses(response, message):
    with pytest.raises(RuntimeError, match=message):
        read_byte_range("https://pds.example/data.img", 10, 12, timeout=30,
                        session=FakeSession(response), product_name="LOLA")
    assert response.closed


@pytest.mark.parametrize(("start", "end"), [(-1, 4), (5, 4)])
def test_read_byte_range_rejects_invalid_bounds(start, end):
    with pytest.raises(ValueError, match="byte range"):
        read_byte_range("https://pds.example/data.img", start, end, timeout=30)
