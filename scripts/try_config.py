from dataclasses import FrozenInstanceError

from app.agents.config import AgentConfig

config = AgentConfig()
print("defaults:", config)

# Check 1: frozen
try:
    config.max_steps = 99
    print("check 1 - FAILED: config was changed")
except FrozenInstanceError:
    print("check 1 - frozen, cannot be changed: True")

# Check 2: the step arithmetic is enforced
try:
    AgentConfig(max_retries=3)  # needs 4 + 9 = 13 steps, default is 12
    print("check 2 - FAILED: bad combination accepted")
except ValueError as error:
    print("check 2 - rejected:", error)

# Check 3: a consistent change is accepted
ok = AgentConfig(max_retries=3, max_steps=13)
print("check 3 - max_retries=3 with max_steps=13 accepted:", ok.max_retries == 3)

# Check 4: widened_top_k above the backend limit is rejected
try:
    AgentConfig(widened_top_k=25)
    print("check 4 - FAILED: 25 accepted")
except ValueError as error:
    print("check 4 - rejected:", error)