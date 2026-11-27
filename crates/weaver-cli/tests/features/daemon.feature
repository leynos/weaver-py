Feature: Manage the weaverd daemon
  Scenario: Start and stop the daemon
    Given a temporary runtime directory
    When I run the cli start command
    Then the daemon should report running status
    When I run the cli stop command
    Then the daemon should not be running

  Scenario: Starting with a missing daemon binary fails
    Given a temporary runtime directory
    When I run the cli start command with a missing binary
    Then the command should exit with failure
    And the daemon should not be running
