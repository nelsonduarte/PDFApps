"""Suite-wide pytest configuration. Registers custom markers only."""


def pytest_configure(config):
    # A test with this marker pins behaviour that is wrong on purpose:
    # it characterises a known defect as the code has it today, so a
    # planned fix makes it fail and it is then rewritten together with
    # that fix. Not an xfail: it must pass today. List them with
    # `pytest -m known_defect`.
    config.addinivalue_line(
        "markers",
        "known_defect(reason): characterises a known defect as it "
        "behaves today; to be rewritten deliberately with the fix "
        "named in reason",
    )
