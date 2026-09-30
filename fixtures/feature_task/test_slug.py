from slug import slugify


def test_slugify_normalizes_words() -> None:
    assert slugify("Hello, World!") == "hello-world"
