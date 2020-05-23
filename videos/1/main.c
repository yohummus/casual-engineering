#include <fcntl.h>
#include <stdio.h>
#include <sys/select.h>
#include <unistd.h>

// Tell clang to ignore missing cases in switch statements
#pragma clang diagnostic ignored "-Wswitch"

// Global countdown; set via FSM actions and decremented in our main loop
int countdown_ms = 0;

// FSM actions (we only have one in this example)
void start_timer(int timeout_ms) {
  countdown_ms = timeout_ms;
}

// Include the generated FSM code here because we need the actions to be
// declared
#include "traffic_lights_fsm.inc"

// Helper function to be able to abort waiting for keyboard input after a
// certain time
char wait_for_keyboard_input(int timeout_ms) {
  fd_set fds;
  FD_ZERO(&fds);
  FD_SET(STDIN_FILENO, &fds);

  struct timeval tv;
  tv.tv_sec  = timeout_ms / 1000;
  tv.tv_usec = (timeout_ms % 1000) * 1000;

  int res = select(1, &fds, NULL, NULL, &tv);

  // Timeout => return 0
  if (res == 0) {
    return 0;
  }

  // Key pressed => return the first character and ignore the rest
  char buffer[100];
  fgets(buffer, sizeof(buffer), stdin);
  return buffer[0];
}

// Main loop; to generate the LightsBroken and LightsRepaired events,
// type the letters b or r respectively, followed by RETURN
int main() {
  State state = init();

  for (;;) {
    printf("State: %s\n", state_to_string(state));

    switch (wait_for_keyboard_input(countdown_ms)) {
      case 0:
        state = post_event(state, kTimeoutEvent);
        break;

      case 'b':
        printf("--- Broke the lights and generated the LightsBroken event\n");
        state = post_event(state, kLightsBrokenEvent);
        break;

      case 'r':
        printf(
            "--- Repaired the lights and generated the LightsRepaired event\n");
        state = post_event(state, kLightsRepairedEvent);
        break;
    }
  }

  return 0;
}
