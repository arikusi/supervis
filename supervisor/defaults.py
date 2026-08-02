"""Provider defaults, in one place.

Their own module because config, session and commands all need them, and any
two of those importing each other would be a cycle.
"""

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_PRO_MODEL = "deepseek-v4-pro"
