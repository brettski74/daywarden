# Work Item Management

The stories folder in the root of this workspace is for holding markdown files that define the stories we plan to work on, are working on or have previously worked on. Stories should be given a story number "Snnn" where "nnn" is a three-digit number. Story numbers should start at 0 and go up incrementally. Larger stories can be defined as epics and broken down into child stories numbered "Snnn.m" where "m" is a number. Typically, we should expect that lower values of m are stories that should be implemented earlier and may be dependencies of later stories, but this is not a strict rule. The main point is to make it clear which stories are part of an epic with this numbering scheme.

Story/Epic documents should start with a data block in a YAML style format that ends with a horizontal separator "---".

Ticket: S001
Title: Implement a thing
Status: ( Draft | Refined | In Progress | Done )
Story Points: 3
Last Updated: yyyy-mm-dd HH:MM:SS
---

Stories and Epics should include the following headings at a minimum:
- User Voice
- Use Cases
- Acceptance Criteria

They may include additional headings as needed, but those should always be there.

Use Fibonnaci numbers when estimating story points and measure story point estimates relative to other similar stories that have been implemented in the past or that we believe are a similar level of effort.

# Testing

Any new feature or bugfix must implement or update at least one automated test. Implement as many tests are are required
to cover the reasonable set of use cases that the new feature or bugfix covers.

For bugfixes and wherever else is practical, prefer to implement tests first, then build the code to make those tests
pass, but this is not a hard rule and if new test cases don't become apparent until after the code is written, this
preference should not be an excuse to avoid writing those tests. The goal is good test coverage, not adherence to some
general guidelines.

Avoid writing pointless tests, such as tests that do nothing but mirror a set of constants, configuration or data and
verify that the other copy is still the same. Similarly, don't write tests whose only purpose is to verify that static
UI elements are still the same statis UI elements we just put into the UI layer. Tests should primarily be about testing
functional code and verifying that the code behaves the way it should, not a duplicate of static content elsewhere.

# Implementation Summary

After implementing a story, append an Implementation section (L1 heading) to the end of the ticket's markdown document with level 2 headings for Files Added/Changed/Removed, Change Summary and Suggested Acceptance Testing. That last section is most important as it should provided a bullet-point list of items that a human reviewer should consider performing on the delivered work.