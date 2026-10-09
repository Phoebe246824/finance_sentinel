"""LiteLLM 调用的默认参数与 provider 归一化。"""

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
