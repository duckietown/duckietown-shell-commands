import os


CONTAINER_BUILD_CACHE_DIR = "/tmp/jb"
LEGACY_HOST_BUILD_CACHE_DIR = "/tmp/duckietown/docs/{book}"
HOME_DIR = os.path.expanduser("~")
FALLBACK_HOST_BUILD_CACHE_DIR = os.path.join(HOME_DIR, ".cache", "duckietown", "docs", "{book}")


def get_host_build_cache_dir(book_name: str) -> str:
    legacy_build_cache = LEGACY_HOST_BUILD_CACHE_DIR.format(book=book_name)
    fallback_build_cache = FALLBACK_HOST_BUILD_CACHE_DIR.format(book=book_name)
    candidate_dirs = (legacy_build_cache, fallback_build_cache)
    for build_cache in candidate_dirs:
        try:
            os.makedirs(build_cache, exist_ok=True)
        except OSError:
            continue
        if os.path.isdir(build_cache):
            return build_cache
    raise OSError(f"Could not create a writable docs build cache directory for '{book_name}'.")
