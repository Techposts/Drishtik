# Phase 7 — Conversation Mode

## Goal
Allow user to ask questions and get snapshots/answers from OpenClaw.

---

## Outcome
- User replies: “Who is that?”
- OpenClaw fetches last snapshot and responds

---

## Inputs
- last event ID
- camera context
- snapshot path

---

## Test Plan

- Send message: “Who is that?”
- Verify reply with summary + snapshot

---

## Done When

- Two-way interaction works
- OpenClaw can answer follow-ups

