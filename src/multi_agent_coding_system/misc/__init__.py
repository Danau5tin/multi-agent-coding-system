import logging


loggers = [
    "LiteLLM Proxy",
    "LiteLLM Router",
    "LiteLLM",

    #added these packages ones below
    "openai",
    "httpx",
    "urllib3.connectionpool",
]
for logger_name in loggers:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.WARNING)