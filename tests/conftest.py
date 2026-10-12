import os

from hypothesis import settings

# "dev" keeps `make check` quick; HYPOTHESIS_PROFILE=thorough runs 1,000 cases per property.
settings.register_profile("dev", max_examples=200, deadline=None)
settings.register_profile("thorough", max_examples=1000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
