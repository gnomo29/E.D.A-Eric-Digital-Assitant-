"""Script autogenerado por ActionAgent."""

from eda.actions import ActionController
from eda.mouse_keyboard import MouseKeyboardController

TASK_NAME = 'auto_abre steam'
TRIGGER = 'abre steam'
STEPS = [{'tool': 'open_dynamic', 'value': 'steam', 'intent': 'open_dynamic', 'preconditions': [], 'dependencies': []}]

def run() -> None:
    actions = ActionController()
    mk = MouseKeyboardController()
    for step in STEPS:
        tool = str(step.get('tool', '')).lower().strip()
        value = step.get('value')
        if tool in {'abrir', 'open', 'open_app', 'open_dynamic'}:
            actions.open_app(str(value))
        elif tool in {'escribir', 'type', 'write'}:
            mk.type_text(str(value))

if __name__ == '__main__':
    run()
