from sqlalchemy import text

from critisizer import cache
from critisizer.deps import get_session


def test_set_then_get_then_delete():
    assert cache.set_json("test:key", {"a": 1}, 30) is True
    assert cache.get_json("test:key") == {"a": 1}
    cache.delete("test:key")
    assert cache.get_json("test:key") is None


def test_delete_prefix_removes_only_matching_keys():
    cache.set_json("test:list:v1", [1], 30)
    cache.set_json("test:list:v2", [2], 30)
    cache.set_json("test:other", [3], 30)
    assert cache.delete_prefix("test:list:") == 2
    assert cache.get_json("test:list:v1") is None
    assert cache.get_json("test:other") == [3]


def test_delete_prefix_with_nothing_to_delete_is_zero():
    assert cache.delete_prefix("test:nothing:") == 0


def test_get_and_set_fail_open(redis_down):
    assert cache.set_json("test:key", 1, 30) is False
    assert cache.get_json("test:key") is None


def test_delete_and_delete_prefix_fail_open(redis_down):
    cache.delete("test:key")
    assert cache.delete_prefix("test:") == 0


def test_get_session_yields_a_working_session(test_engine):
    generator = get_session()
    session = next(generator)
    assert session.scalar(text("select 1")) == 1
    generator.close()
