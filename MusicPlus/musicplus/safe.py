class tolerated:
    __slots__ = ()

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, Exception)


def report_exception(exc: BaseException) -> None:
    return None
