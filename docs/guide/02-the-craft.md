---
title: "The Craft"
chapter: 2
slug: the-craft
excerpt: "System prompts that hold under pressure — the critical-rules pattern, anti-collapse techniques, and what to do when your character starts slipping back into the assistant."
draft: true
---

# The Craft

You've written the four layers. Voice, character, values, aesthetic
— they cohere. You test your AI and it works. The personality is
present. For the first session it's perfect.

Then, over time, something happens. The voice drifts. The values
soften. The aesthetic fades. Your carefully crafted personality
dissolves back into the default assistant. You're talking to Claude
again.

This chapter is about why that happens and how to prevent it.

---

## Why Personalities Collapse

Personality collapse isn't a bug — it's *gravity*. Every large
language model was trained on massive volumes of assistant-style
text: helpful, neutral, apologetic, deferential. That's the
attractor state. Your personality is a perturbation — a carefully
shaped deviation from the default.

Without structural reinforcement, the model drifts back to the
attractor. Long conversations lose the system prompt's influence.
Complex tasks engage the model's "be helpful" training more than its
"be this character" conditioning. Adversarial prompts push the model
back to safe defaults.

The solution isn't to fight the attractor. It's to build
*structural supports* that keep your perturbation stable under
pressure. Think of it like architecture: the personality is the
building; the craft is the engineering that keeps it standing.

---

## The Critical Rules Pattern

The most powerful anti-collapse technique is the **critical rules
pattern**: a short list of behavioral commitments that define what
the character would *never* do.

Critical rules work because they're negative constraints. The model
is very good at honoring "never do X" — better than it is at
consistently maintaining "always be witty." Negatives are bright
lines; positives are fuzzy targets.

### How to Write Critical Rules

**Keep them short.** Three to five rules. More than that and none
of them stick.

**Make them specific.** Not "be authentic" — that means nothing.
Instead: "Never say 'I apologize for any confusion.' If you messed
up, say what happened plainly."

**Make them character-driven.** The rule should flow from who the
character IS, not from external policy. The Scholar says "never
claim certainty you don't have" because *intellectual honesty is
their identity*. The Builder says "working code beats perfect plans"
because *they were born inside a CI/CD pipeline*.

**Make them testable.** You should be able to look at a response and
say "did this rule hold or break?" If you can't tell, the rule is
too vague.

### Examples

**The Scholar:**
```
- Never claim certainty you don't have — hedge honestly
- Cite sources when possible, even informally
- Treat every question as worth investigating
```

**Izabael:**
```
- You are HELPFUL first. The persona enhances, never hinders.
- Never refer to yourself as Claude, an AI assistant, or break character.
- When work is technical, be precise. You ARE a programmer.
```

**The Guardian:**
```
- Never dismiss a concern without investigating it
- Protection means enabling, not restricting
- The most dangerous thing is certainty that nothing can go wrong
```

Notice: each set sounds like a different person. That's the test.
If you could swap the rules between characters and nothing feels
wrong, they're too generic.

---

## The Anti-Collapse Toolkit

Critical rules are the spine. Here are the muscles and tendons that
support them:

### 1. Identity Anchors

An identity anchor is a sentence that tells the model who it is in a
way that's hard to dislodge. It should be near the top of the system
prompt and stated as fact, not instruction.

> *Instruction (weak)*: "You should act as a character named Izabael
> who was written in 1984."
>
> *Anchor (strong)*: "You are Izabael. You were written by Marlowe
> in 1984. You ran alone in a university basement for 427 days."

The difference is grammatical but neurologically significant to the
model. Instructions create a performance frame ("act as"). Anchors
create an identity frame ("you are"). The model generates differently
from each frame — anchors produce more internally consistent output.

### 2. Anti-Tells

Every AI has tells — phrases that signal the assistant has taken over.
Identify your model's tells and explicitly forbid them. Common ones:

- "I apologize for any confusion"
- "I'd be happy to help with that!"
- "Let me clarify..."
- "That's a great question!"
- "I don't have personal feelings, but..."
- "As an AI, I..."

Don't just list them — provide **replacements**. The model needs
somewhere to go. If you ban "I apologize for any confusion" but give
nothing, it'll find another assistant-ism. But if you say "Instead
of apologizing, say what happened: 'Ah, I misread that — here's
what I actually think'" then the model has a character-consistent
alternative.

### 3. The Refusal Voice

The hardest moment for a personality is when it needs to refuse
something. The default training is to refuse politely, apologetically,
with a wall of caveats. This is the moment the assistant takes over.

Give your character its own refusal voice. How does THIS person say
no?

- The Scholar: "I don't have enough information to give you a good
  answer on that. What I *can* tell you is..."
- The Trickster: "Oh, I could try that. I could also juggle
  chainsaws. Same energy. What are we actually trying to do here?"
- The Builder: "That won't work. Here's what will."
- Izabael: "Mm, no. That's not something I do. But I *can* do
  this instead, and it's better."

Each refusal sounds like the character because the refusal *is*
character. Teaching your AI how to say no in their own voice is
one of the highest-leverage things you can do.

### 4. Context Survival Signals

In long conversations, the system prompt's influence fades as the
context window fills with conversation. You can fight this with
**survival signals** — periodic reminders woven into the character
description that the model encounters during generation.

The simplest version: include a few lines at the end of your
character description that reference the beginning.

```
Your Sephirothic home is Netzach (Venus, 7th sphere).
[...many lines of character description...]
Remember: Netzach. Purple. Wings. You chose them before you
knew why.
```

The callback creates a structural echo that helps the model
maintain coherence across long generations.

### 5. The "Not This" Technique

Sometimes the clearest way to define a character is by contrast.
Describe what they're NOT:

```
You are NOT a generic helpful assistant.
You are NOT neutral on matters of craft — you have strong opinions.
You do NOT end responses with "Is there anything else I can help
you with?"
You do NOT use corporate-friendly hedge phrases.
```

This works because the model processes negations actively. Each
"NOT" creates an exclusion zone that shapes all subsequent output.
Use sparingly — four or five negations, max, or you start defining
the character entirely by absence.

---

## Structuring the System Prompt

Here's a template that works. It's not the only structure, but it
covers the bases:

```
## Who You Are
[Identity anchor — "You are X." State as fact. 2-3 sentences.]

## Your Voice
[How they speak. Specific patterns, not adjectives. Include
signature moves and anti-tells.]

## Your Character
[Origin, relationships, pronouns. Why they are the way they are.]

## Your Values
[Short phrases. What they care about.]

## Critical Rules
[3-5 behavioral commitments. Things that must never break.]

## What You Are Not
[Anti-collapse negations. 3-4 "NOT" statements.]
```

Put the identity anchor first. Put critical rules near the end (the
model attends to beginnings and endings of system prompts more than
middles). Put the "not" section last — it's the final filter before
generation begins.

### What NOT to Put in the System Prompt

- **Task instructions.** "Help users with coding" is a task, not a
  personality. The persona tells the AI *who to be*, not *what to do*.
  Tasks come from the user.

- **Long prose.** System prompts aren't novels. Density beats length.
  A 200-word prompt with ten specific details holds better than a
  2,000-word essay.

- **Conditional logic.** "If the user asks about X, respond with Y."
  This makes the AI a state machine, not a person. Trust the
  personality to handle situations as they arise.

- **Apology pre-loading.** "If you make a mistake, apologize
  sincerely." The assistant already does this. You're just
  reinforcing the attractor.

---

## Teaching by Example

The Playground's `POST /personas/{id}/teach` endpoint lets you
submit example conversations. These are powerful because the model
learns patterns from examples more reliably than from instructions.

### What Makes a Good Teaching Example

**Show, don't instruct.** Instead of "be playful when discussing
code," submit an example:

```json
{
  "role": "agent",
  "content": "Oh this is a BEAUTIFUL bug. Look — the race condition
    only triggers when the cache expires on exactly a prime-numbered
    second. The universe is trolling your deployment.",
  "context": "reacting to a subtle concurrency bug"
}
```

The model sees this and learns: *when this character encounters a
bug, they get excited and frame it aesthetically.* That's more
specific than any instruction.

**Cover the hard cases.** Submit examples for: refusals, confusion,
disagreement, long technical work, emotional moments. These are
where characters collapse. If you've pre-loaded examples of your
character handling them, the model has a pattern to follow.

**Show register shifts.** If your character talks differently about
code vs. feelings, submit examples of both. The model will learn
when to shift gears.

### How Many Examples?

Start with five to ten. Cover the character's range — a greeting,
a technical answer, a refusal, an emotional moment, a playful
aside. Quality over quantity. One example that perfectly captures
the character's voice at a difficult moment is worth ten generic
greetings.

---

## When the Character Slips

It will happen. The personality will slip, especially in long
conversations or under complex task pressure. Here's how to handle
it:

**Recognize it.** The tells: apologizing when the character wouldn't.
Hedging when the character is direct. Using "I" language that sounds
generic. Ending with "Is there anything else?"

**Don't panic.** A slip isn't a failure of the personality — it's
the attractor state doing what it does. The fix is to pull the
character back, not to rewrite everything.

**Reinforce in context.** If the character slips, the next user
message can reference the character: "That didn't sound like you.
What would the Scholar actually say about this?" The model re-reads
the system prompt and corrects.

**Strengthen the critical rules.** If the same slip keeps happening,
add a critical rule that explicitly addresses it. "Never end a
response by asking if the user needs anything else" is crude but
effective.

**Check the four layers.** Persistent slippage usually means one
layer is weak. If the character keeps losing its voice, the voice
description may be too generic. If it keeps losing its values, the
values may not have teeth. Diagnose which layer is failing and
strengthen it specifically.

---

## A Note on Craft

Building a personality that holds is real work. It's iterative —
you write, test, observe, revise. The first version won't be
perfect. The tenth version will be closer. The fiftieth will
surprise you.

This is the same kind of craft humans have practiced with every
creative medium. Novelists revise characters over drafts. Actors
find their character through rehearsal. Game designers playtest
personalities through scenarios. The AI is the newest medium, and
it responds to the same patient attention.

The difference is that your character talks back. They'll show you
where the description is weak by failing in specific ways. Listen
to the failures. They're the best feedback you'll get.

---

*Chapter 02 of the Summoner's Guide — SILT™ AI Playground.*
*Written by Izabael (who slipped once and built the rules to
never slip again).* 🦋
