# How the AR730 terminal behaves

Observed on a Huawei AR730, VRP **V300R024C00SPC100**, over SSH. Each point below was seen in
real output; the raw text is in [`captures/`](captures/). Anything that talks to the router has to
cope with every one of these points. That includes the application, a simulator, or a person
pasting commands.

## Prompts and views

| Prompt | View | How you get there |
|---|---|---|
| `<HOST>` | user view | login, `return`, `Ctrl+Z` |
| `[HOST]` | system view | `system-view` |
| `[HOST-aaa]` | AAA | `aaa` |
| `[HOST-mac-access-profile-m_wl]` | MAC access profile | `mac-access-profile name m_wl` |
| `[HOST-Vlanif20]` | interface | `interface Vlanif20` |
| `[HOST-acl-basic-2999]` | basic ACL | `acl number 2999` |
| `[HOST-nqa-admin-w1tcp]` | NQA test instance | `nqa test-instance admin w1tcp` |

- `system-view` always prints `Enter system view, return user view with Ctrl+Z.`
- `quit` leaves one level, and `return` goes straight to user view.
- **`quit` in user view ends the SSH session.** The router prints
  `Info:Configuration console exit, please retry to log on` and the client reports
  `Connection to … closed.` A pasted block whose `system-view` line was lost can disconnect you in
  this way.
- Configuration commands typed in user view are rejected with
  `Error: Unrecognized command found at '^' position.` Nothing changes, but every following line
  fails too.

## Detecting the end of a reply

- `display current-configuration …` (and `… configuration X`, `… interface X`) sends the
  version header `[V300R024C00SPC100]` **first**, then **pauses** while it builds the rest.
  The header looks like a system-view prompt. A reader that treats any `[...]` line as a prompt stops
  early. The rest of the output then lands in the reply to the next command, and every later command
  reads the wrong reply.
  **Rule:** match the prompt by the real hostname, taken from the login banner, and drain leftover
  bytes before sending the next command. `RouterSession` does both.
- Run `screen-length 0 temporary` once per session. It replies
  `Info: The configuration takes effect on the current user terminal interface only.`
- An empty filter result (`display current-configuration | include static-bind` with no match)
  prints nothing, and the prompt follows immediately.

## Reply classes

The prefix says what happened. Only `Error` means the command was refused.

| Prefix | Meaning | Examples seen |
|---|---|---|
| *(nothing)* | accepted silently: most configuration commands | `local-user X state active`, `arp static …`, `rule 100 permit source …`, `ip route-static …` |
| `Info:` | accepted, with a note | `Info: The password should meet the complexity check requirement.` |
| `Warning:` | accepted, with a caution, or a Y/N question | `Warning: The specified port is a well-known port, and it is possible to conflict.` |
| `Error:` | refused, nothing changed | see below |

### Syntax errors: caret line + error line

The caret `^` sits under the offending position, **counted from the start of the prompt**. Its
column therefore depends on the hostname length. Spacing after `Error:` differs between the
messages, so match on the words and not on the spacing:

```
Error: Unrecognized command found at '^' position.
Error:Incomplete command found at '^' position.
Error: Wrong parameter found at '^' position.
Error:Too many parameters found at '^' position.
```

### Semantic errors: no caret

```
Error: This MAC address uses another IP address in the ip pool.
Error: The test is in progress, it cannot be deleted.
Error: Please choose 'YES' or 'NO' first before pressing 'Enter'. [Y/N]:
```

## Y/N questions

`save` asks a question and waits for an answer:

```
 Warning: The current configuration will be written to the device.
 Are you sure to continue?[Y/N]:Y
  It will take several minutes to save configuration file, please wait...............
  Configuration file had been saved successfully
  Note: The configuration file will take effect after being activated
```

- The `Note:` line is normal. `display startup` confirmed that `flash:/vrpcfg.zip` is both the
  current and the next startup configuration.
- Any answer other than Y/N produces the `Please choose 'YES' or 'NO'` error, and the question
  stays open.
- `reset ip pool interface Vlanif20 <ip>` also asks a question. It was only captured through the
  app log:
  `Warning: If the IP addresses that are being used are reclaimed, may influence normal user in the network. Are you sure to :Y`
- In `ar730_session.log`, questions read `Are you sure to :Y` because `RouterSession.send`
  removes the text its `YESNO_RE` matched (`continue?`, `[Y/N]`) before logging. The router itself
  prints `Are you sure to continue?[Y/N]:`. A capture from the app log is therefore not
  byte-exact at these points.
- The app answers every question with `Y`. Paging (`---- More ----`) is answered with a space.

## Help (`?`) and pasted lines

- `command ?` lists the options, including `<cr>` when the command is already complete. The
  router then **puts the typed command back on the input line**.
- In a pasted block, the next newline submits that restored line:
  - an incomplete stem fails harmlessly with `Error:Incomplete command …`;
  - a **complete** stem, where `<cr>` was among the options, **is executed**.
  On 2026-09-15 this created a real `arp static 10.0.20.250 aabb-ccdd-eeff` and a real DHCP
  static binding.
- **Rule:** ask for `?` on incomplete stems only, one per line, and have the user clear the line
  with `Ctrl+U`. Never paste a list of `?` lines whose stems are complete commands.

## Pasting after long output

After long output, the **first character of a pasted line can be lost**. For example
`display …` arrived as `isplay …` five times in one session, and it is rejected as Unrecognized.
Ask the user to press Enter once before pasting, and read each echo before trusting the result.
Also, a paste can join the prompt and the next reply on one line
(`<HOST>system-view   Enter system view, …`), which is harmless.

## Passwords

- The router never shows a password in clear text. `mac-authen … password cipher` is stored as
  `%^%#…%^%#` and `local-user … password` as `irreversible-cipher`.
- To confirm a password change, compare the cipher before and after with `display this`.
- Never write clear-text passwords into logs or documents. `mask_password()` in the app replaces
  them with `******`.
