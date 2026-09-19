# data/

`oui.dat` — IEEE MAC vendor registry, zlib-compressed `PREFIX<TAB>NAME` lines.

Built on 2026-09-17 from the three IEEE registries (53,941 assignments):

| Registry | Prefix length | Source |
|---|---|---|
| MA-L | 24 bit (6 hex) | `https://standards-oui.ieee.org/oui/oui.csv` |
| MA-M | 28 bit (7 hex) | `https://standards-oui.ieee.org/oui28/mam.csv` |
| MA-S | 36 bit (9 hex) | `https://standards-oui.ieee.org/oui36/oui36.csv` |

Organisation names are whitespace-collapsed, stripped of trailing legal suffixes
(Inc., Ltd., GmbH …) and cut at 38 characters. An assignment registered without a
public name (`Private`, 649 of them) is stored as `\x00`, which the application
shows as "undisclosed vendor" — this is deliberately different from a prefix that
is not registered at all, which shows the raw prefix.

`mac_vendor()` tries the longest assignment first (9, then 7, then 6 hex digits),
because a small company's 36-bit block sits inside a large company's 24-bit block.

A MAC whose locally-administered bit is set is randomised and has no vendor; the
application says so instead of looking it up.

To refresh: download the three CSVs and rebuild with the same rules. The file is
optional — if it is missing the application falls back to showing the prefix.
