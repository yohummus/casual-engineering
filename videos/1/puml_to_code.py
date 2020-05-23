#!/usr/bin/env python3

import pathlib
import re
import subprocess
import sys
from typing import NamedTuple, List, Optional, Tuple, Dict, Callable


# ========== TYPE DEFINITIONS ==========

class Line(NamedTuple):
    """Represents a single line in a .puml file"""
    filename: str
    line_no: int
    orig_text: str
    text: str

    def __str__(self):
        return f'{self.filename}:{self.line_no}'


class Event(NamedTuple):
    """Represents an event in the FSM"""
    name: str


class Guard(NamedTuple):
    """Represents a guard transition in the FSM"""
    code: str


class Action(NamedTuple):
    """Represents an action in the FSM"""
    code: str


class Transition(NamedTuple):
    """Represents a transition in the FSM"""
    event: str
    guard: Optional[Guard]
    from_state: 'State'
    to_state: 'State'
    actions: List[Action]

    def __str__(self):
        guard_str = '' if not self.guard else f' [{self.guard.code}]'
        return f'{self.from_state.name} --- {self.event.name}{guard_str} --> {self.to_state.name}'

    def __repr__(self):
        return str(self)


class State(NamedTuple):
    """Represents a state in the FSM"""
    name: str
    parent_state: Optional['State']
    child_states: 'StateDict'
    is_initial_state: bool
    out_transitions: List[Transition]
    int_transitions: List[Transition]
    entry_transitions: List[str]
    exit_transitions: List[str]

    def __str__(self):
        parent = 'None' if not self.parent_state else self.parent_state.name
        transition_nums = ', '.join([f'{len(self.out_transitions)} out',
                                     f'{len(self.int_transitions)} int',
                                     f'{len(self.entry_transitions)} entry',
                                     f'{len(self.exit_transitions)} exit'])

        return f'State {self.name}: ' + ', '.join([
            f'parent={parent}',
            f'children={len(self.child_states)}',
            f'initial={self.is_initial_state}',
            f'transitions=({transition_nums})',
        ])

    def __repr__(self):
        return str(self)


StateDict = Dict[str, State]
EventDict = Dict[str, Event]


# ========== FUNCTIONS FOR PARSING THE PUML FILES ==========

def parse_puml_file(filename: str) -> StateDict:
    """Parses the FSM definition in the given .puml file"""
    lines = cleanup_lines(read_puml_file(filename))

    initial_state_names, lines = parse_initial_state_transitions(lines)
    states, lines = parse_states(lines, initial_state_names)
    check_initial_states_exist(initial_state_names, states)
    check_states(states)

    lines = parse_transitions(states, lines)

    assert not lines, 'No idea how to parse the following lines:' + ''.join([f'\n{x}: {x.orig_text}' for x in lines])

    return states


def read_puml_file(filename: str) -> List[Line]:
    """Reads the .puml file into a list of lines"""
    with open(filename, 'r') as f:
        content = f.read()

    return [Line(filename, i + 1, x, x) for i, x in enumerate(content.split('\n'))]


def cleanup_lines(lines: List[Line]) -> List[Line]:
    """Removes empty lines and uninteresting things from non-empty lines"""
    clean_lines = []
    for filename, line_no, orig_text, text in lines:
        if any(text.startswith(x) for x in ['@', 'title ', 'hide empty ', 'note ']):
            text = ''
        else:
            text = re.sub(r'#\w+', '', text)
            text = text if "'" not in text else text[:text.index("'")]
            text = text.strip()

        if text:
            clean_lines.append(Line(filename, line_no, orig_text, text))

    return clean_lines


def parse_initial_state_transitions(lines: List[Line]) -> Tuple[Dict[str, Line], List[Line]]:
    """Extracts the initial states and returns only the remaining lines"""
    remaining_lines = []
    initial_state_names = {}

    for line in lines:
        m = re.fullmatch(r'^\[\*\]\s+-{1,2}>\s+(\w+)\s*(.*)', line.text)
        if not m:
            remaining_lines.append(line)
            continue

        name, trailing_text = m.groups()
        assert name not in initial_state_names, f'Duplicate initial transition for state {name} in {line}'
        assert not trailing_text, f'Additional text after initial transition in {line}: {line.orig_text}'
        initial_state_names[name] = line

    return initial_state_names, remaining_lines


def parse_states(lines: List[Line], inital_state_names: Dict[str, Line]) -> Tuple[StateDict, List[Line]]:
    """Extracts all states and returns only the remaining lines"""
    remaining_lines = []
    states = {}
    state_stack = [None]

    for line in lines:
        if line.text == '}':
            state_stack.pop()
            assert state_stack, f'Closing brace }} in {line} does not match any opening brace'
            continue

        m = re.fullmatch(r'^(state\s+)?(\w+)\s*(:\s*(.*?)\s*)?(\{?)$', line.text)
        if not m:
            remaining_lines.append(line)
            continue

        _, name, _, trans_txt, open_brace = m.groups()
        parent_state = state_stack[-1]
        state = states.setdefault(name, State(name, parent_state, [], name in inital_state_names, [], [], [], []))

        if parent_state and state not in parent_state.child_states:
            parent_state.child_states.append(state)

        if trans_txt:
            transition = parse_transition_line(line, trans_txt, state, state)
            if transition.event.name == 'entry':
                state.entry_transitions.append(transition)
            elif transition.event.name == 'exit':
                state.exit_transitions.append(transition)
            else:
                state.int_transitions.append(transition)

        if open_brace:
            state_stack.append(state)

    return states, remaining_lines


def check_initial_states_exist(inital_state_names: Dict[str, Line], states: StateDict) -> None:
    """Checks that every state in the list of initial state names actually exists"""
    for name, line in inital_state_names.items():
        assert name in states, f'The target state "{name}" of the initial transition in {line} has not been defined'


def check_states(states: StateDict) -> None:
    """Checks for errors in the states such as missing initial states"""
    names = [x.name for x in states.values() if x.parent_state is None and x.is_initial_state]
    assert names, f'No initial top level state specified'
    assert len(names) == 1, f'Multiple initial top level states specified: {", ".join(names)}'

    for state in states.values():
        if not state.child_states:
            continue

        names = [x.name for x in state.child_states if x.is_initial_state]
        assert names, f'No initial state specified in composite state {state.name}'
        assert len(names) == 1, f'Multiple initial states specified in composite state {state.name}'


def parse_transitions(states: StateDict, lines: List[Line]) -> List[Line]:
    """Extracts all transitions and puts them into the state definitions"""
    remaining_lines = []

    for line in lines:
        m = re.fullmatch(r'^(\w+)\s+-{1,2}>\s(\w+)\s*(:\s*(.*?)\s*)?', line.text)
        if not m:
            remaining_lines.append(line)
            continue

        from_state, to_state, _, trans_txt = m.groups()
        assert trans_txt, f'Missing event in transition in {line}: {line.orig_text}'
        assert from_state in states, f'State "{from_state}" in {line} has not been defined'
        assert to_state in states, f'State "{to_state}" in {line} has not been defined'

        transition = parse_transition_line(line, trans_txt, states[from_state], states[to_state])
        states[from_state].out_transitions.append(transition)

    return remaining_lines


def parse_transition_line(line: Line, trans_txt: str, from_state: State, to_state: State) -> Transition:
    """Creates a transition from the text on a transition or inside a state"""
    m = re.fullmatch(r'^(\w+)\s*(\[\s*(.*?)\s*\]\s*)?(/(.*))?', trans_txt.replace('\\n', ''))
    assert m, f'Invalid transition format in {line}: {line.orig_text}'

    event_name, _, guard_code, _, actions_txt = m.groups()
    actions_code = [] if not actions_txt else [x.strip() for x in actions_txt.split('/') if x.strip()]

    event = Event(event_name)
    guard = None if not guard_code else Guard(guard_code)
    actions = [Action(x) for x in actions_code]
    transition = Transition(event, guard, from_state, to_state, actions)

    return transition


# ========== FUNCTIONS FOR THE CODE GENERATION ==========

def generate_fsm_header_file(states: StateDict, namespace: str) -> str:
    """Generates the code for the FSM"""
    events = get_event_names(states)

    initial_state = [x for x in states.values() if x.parent_state is None and x.is_initial_state][0]
    while initial_state.child_states:
        initial_state = [x for x in initial_state.child_states if x.is_initial_state][0]

    return f'''
// ===== States =====
typedef enum {{
  {''.join(f'k{x}State,' for x in states.keys())}
}} State;

const char* state_to_string(State state) {{
  switch (state) {{
    {''.join(f'case k{x}State: return "{x}";' for x in states.keys())}
    default: return "???";
  }}
}}

// ===== Events =====
typedef enum {{
  {''.join(f'k{x}Event,' for x in events)}
}} Event;

const char* event_to_string(Event event) {{
  switch (event) {{
    {''.join(f'case k{x}Event: return "{x}";' for x in events)}
    default: return "???";
  }}
}}

// ===== State entry/exit actions =====
void call_state_entry_actions(State state) {{
  switch (state) {{
    {makeStateEntryExitActionsSwitchCode(states, lambda state: state.entry_transitions)}
  }}
}}

void call_state_exit_actions(State state) {{
  switch (state) {{
    {makeStateEntryExitActionsSwitchCode(states, lambda state: state.exit_transitions)}
  }}
}}

// ===== FSM initialization =====
State init() {{
  {makeInitStateEntryCode(initial_state)}
  return k{initial_state.name}State;
}}

// ===== FSM event handling =====
State post_event(State cur_state, Event event) {{
  State new_state = cur_state;

  switch (event) {{
    {makePostEventSwitchCode(states)}
  }}

  return new_state;
}}
    '''


def get_event_names(states: StateDict) -> List[str]:
    """Returns a list containing all event names sorted alphabetically"""
    transitions = []
    for state in states.values():
        transitions += state.int_transitions
        transitions += state.out_transitions

    return sorted(list({trans.event.name for trans in transitions}))


def makeStateEntryExitActionsSwitchCode(states: StateDict, transitions_getter: Callable[[State], List[Transition]]) -> str:
    """Creates the code inside the switch statement for state entry/exit actions"""
    code = ''
    for state in states.values():
        transitions = transitions_getter(state)
        if not transitions:
            continue

        code += f'case k{state.name}State:'
        code += makeTransitionsActionCode(transitions)
        code += 'break;'

    return code


def makeTransitionsActionCode(transitions: List[Transition]) -> str:
    """Creates the code for executing the actions for the given transitions if their guard condition is met"""
    code = ''
    for transition in transitions:
        action_code = ''.join([f'{x.code};' for x in transition.actions])
        if not action_code:
            continue

        action_block = f'{{ {action_code} }}'
        if transition.guard:
            code += f'if ({transition.guard.code})'
        code += action_block

    return code


def makePostEventSwitchCode(states: StateDict) -> str:
    """Creates the code inside the switch statement for the event posting function"""
    code = ''
    for event_name in get_event_names(states):
        code += f'''
            case k{event_name}Event:
              switch (cur_state) {{
                {makePostEventStateSwitchCode(event_name, states)}
              }}
              break;
        '''

    return code


def makePostEventStateSwitchCode(event_name: str, states: StateDict) -> str:
    """Creates the code inside the switch statement for states inside the case for the given event"""
    code = ''
    for state in states.values():
        case_code = makePostEventStateSwitchCaseCode(event_name, state, states)
        if case_code:
            code += f'''
                case k{state.name}State:
                  {case_code}
                  break;
            '''

    return code


def makePostEventStateSwitchCaseCode(event_name: str, current_state: State, states: StateDict) -> str:
    """Creates the code for the switch case that handles the given event in the given state"""
    code = ''

    state = current_state
    while state:
        # First check for internal transitions
        int_trans = [x for x in state.int_transitions if x.event.name == event_name]
        if int_trans:
            code += f'// Internal transition(s) on event {event_name}\n'
            code += makeTransitionsActionCode(int_trans)
            break

        # If there are no internal transitions, then look at the outgoing transitions
        out_trans = [x for x in state.out_transitions if x.event.name == event_name]
        if out_trans:
            for trans in out_trans:
                code += f'// {trans}\n'

                if trans.guard:
                    code += f'if({trans.guard.code})'

                code += '{'

                # Call the exit actions
                states_exited = [current_state]
                while states_exited[-1] is not state:
                    states_exited.append(states_exited[-1].parent_state)
                if state.parent_state:
                    states_exited.append(state.parent_state)

                for st in states_exited:
                    code += f'call_state_exit_actions(k{st.name}State);'

                # Call the transition actions
                code += makeTransitionsActionCode([trans])

                # Call the entry actions
                states_entered = [trans.to_state]
                while states_entered[0].parent_state not in [state, None]:
                    states_entered.insert(0, states_entered[0].parent_state)
                while states_entered[-1].child_states:
                    initial_child_state = [x for x in states_entered[-1].child_states if x.is_initial_state][0]
                    states_entered.append(initial_child_state)

                for st in states_entered:
                    code += f'call_state_entry_actions(k{st.name}State);'

                # Set the new/next state
                new_state = states_entered[-1]
                code += f'new_state = k{new_state.name}State;'

                code += 'break;'
                code += '}'

            break

        # Go up one level in the state hierarchy
        state = state.parent_state

    return code


def makeInitStateEntryCode(initial_state: State) -> str:
    """Creates the code inside the main() function for calling all state entry function to get to the initial state"""
    # Call the entry actions
    states_entered = [initial_state]
    while states_entered[0].parent_state:
        states_entered.insert(0, states_entered[0].parent_state)

    code = ''
    for st in states_entered:
        code += f'call_state_entry_actions(k{st.name}State);'

    return code


# ========== AUTO-FORMATTING ==========

def run_clang_format(filename: str) -> None:
    """Runs clang-format on the given file"""
    subprocess.run(['clang-format', '-assume-filename=fsm.h', '-i', filename])


# ========== MAIN ==========

if __name__ == '__main__':
    for filename in pathlib.Path(__file__).parent.rglob('*.puml'):
        output_filename = filename.with_suffix(".inc")
        print(f'Generating {output_filename}...')

        states = parse_puml_file(str(filename))
        code = generate_fsm_header_file(states, filename.stem)

        with open(output_filename, 'w') as f:
            f.write(code)

        run_clang_format(output_filename)
