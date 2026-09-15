# FoodOn Avoidance Graph — opening it the first time

This app is not signed with an Apple Developer certificate, so macOS will refuse to
open it until you say otherwise. It is one extra step, once.

1. Open `FoodOn Avoidance.dmg` and drag **FoodOn Avoidance** into **Applications**.
2. Double-click it. macOS blocks it: *"Apple could not verify FoodOn Avoidance is free
   of malware."*  Click **Done**.
3. Open **System Settings → Privacy & Security**, scroll to the bottom. There is a line
   about FoodOn Avoidance being blocked, and a button: **Open Anyway**. Click it, and
   confirm with Touch ID or your password.
4. It opens from then on by double-clicking, with no further prompts.

A small window appears saying it is running, and your browser opens on the graph. To
stop it, click **Quit** in that window — closing the browser tab leaves it running.

## What it is

Type an ingredient (`paprika`, `edamame`) or a class (`nightshade`, `allium`, `gluten`)
and it shows everything that should be treated as containing it, with the path that
justifies each one. Nothing leaves your machine: the server is local, bound to
localhost, and there is no network call anywhere in it.

This is an **explore-only** build. The editing interface, which changes the signed
decisions behind the graph, is not included — so nothing you do here can alter the
results, and there is nothing you can break.

## Requirements

An **Apple Silicon** Mac (M1 or later) running a recent macOS. It will not run on an
Intel Mac; that needs a separate build.

## What it is not

Not a medical device, and not clinical advice. The relationships come from FoodOn plus
a layer of human judgements, and the `Known limits` section of the project README is an
honest list of what it does not catch.
