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

