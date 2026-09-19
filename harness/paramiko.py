# -*- coding: utf-8 -*-
"""
راوتر AR730 وهمي يتكلم VRP عبر قناة SSH وهمية.

يحاكي ما رأيناه فعلاً على الجهاز:
  - صدى الأمر ثم موجّه الأوامر <AR730> أو [AR730-aaa]
  - أسئلة [Y/N] عند save
  - رفض ترتيب service-type الخاطئ
  - رفض كلمة سر تساوي اسم المستخدم
  - display current-configuration configuration aaa / display user-group /
    display access-user / cut access-user
"""
import re
import zlib


class AuthenticationException(Exception): pass
class SSHException(Exception): pass
class AutoAddPolicy(object): pass


class FakeAR730(object):
    def __init__(self):
        self.hostname = "AR730"
        self.view = "user"          # user | system | aaa
        self.users = {}             # name -> {"types":set,"group":str|None,"pw":bool}
        self.groups = {"grp_managers": "3010", "grp_staff": "3020", "grp_infra": "3030"}
        self.online = []            # dicts
        self.saved = False
        self.save_count = 0
        self.cut_log = []
        self.history = []
        self.profiles = {}          # mac-access-profile -> كلمة السر (نص واضح للفحص)
        self.profile = None
        self.reject_profile_pw = False     # لمحاكاة رفض الراوتر لكلمة سر الملف
        self.reject_pw_for = set()         # حسابات يرفض الراوتر تحديث كلمة سرها
        self.wan = None                    # يُنشأ عند أول أمر خطوط (يحتاج ar730_manager)
        self.mgmt = None                   # أجهزة الإدارة، مثل wan
        self.sub = ""                      # اسم عرض interface أو acl
        self._seed()

    def _seed(self):
        self.users["admin"] = {"types": {"ssh", "http", "terminal"}, "group": None,
                               "pw": True, "priv": 15}
        self.users["00005e005302"] = {"types": {"8021x"}, "group": "grp_managers", "pw": True,
                                      "pwval": "Old-Shared-1", "state": "A"}
        self.profiles["m_wl"] = "Old-Shared-1"
        self.profiles["mac_access_profile"] = None
        self.online = [
            {"id": "1032", "user": "00005e005302", "ip": "10.0.20.166",
             "mac": "0000-5e00-5302", "status": "Success"},
            {"id": "1027", "user": "00005e005301", "ip": "10.0.21.207",
             "mac": "0000-5e00-5301", "status": "Pre-authen"},
        ]

    # -- الموجّه --------------------------------------------------------------
    def prompt(self):
        if self.view == "user":
            return "<%s>" % self.hostname
        if self.view == "system":
            return "[%s]" % self.hostname
        if self.view == "macprof":
            return "[%s-mac-access-profile-%s]" % (self.hostname, self.profile)
        if self.view == "sub":
            return "[%s-%s]" % (self.hostname, self.sub)
        return "[%s-aaa]" % self.hostname

    # -- تنفيذ أمر ------------------------------------------------------------
    def run(self, cmd):
        cmd = cmd.strip()
        self.history.append((self.view, cmd))
        if not cmd:
            return ""

        if cmd in ("system-view", "sys"):
            self.view = "system"; return ""
        if cmd == "aaa":
            if self.view != "system":
                return "Error: Unrecognized command found at '^' position."
            self.view = "aaa"; return ""
        if cmd == "quit":
            self.view = {"aaa": "system", "macprof": "system", "sub": "system",
                         "system": "user", "user": "user"}[self.view]
            return ""
        if cmd == "return":
            self.view = "user"; return ""
        if self.mgmt is None:
            import ar730_manager
            self.mgmt = ar730_manager._DemoMgmt()
        mg = self.mgmt.run(cmd, self)
        if mg is not None:
            return mg
        if cmd.startswith("mac-access-profile name "):
            if self.view != "system":
                return "Error: Unrecognized command found at '^' position."
            self.profile = cmd.split()[2]
            self.profiles.setdefault(self.profile, None)
            self.view = "macprof"; return ""
        if cmd.startswith("mac-authen "):
            if self.view != "macprof":
                return "Error: Unrecognized command found at '^' position."
            if self.reject_profile_pw:
                return "Error: The password does not meet the complexity requirement."
            self.profiles[self.profile] = cmd.split()[-1]
            return "Info: The password should meet the complexity check requirement."
        if cmd.startswith("screen-length"):
            return ""
        if cmd == "save":
            self.saved = True; self.save_count += 1
            return "__SAVE__"

        if self.wan is None:
            # محاكي الخطوط موجود في البرنامج نفسه (لوضع التجربة)، ومخرجاته
            # منسوخة عن الجهاز الحقيقي؛ نستورده متأخراً لأن هذا الملف يُحمَّل قبله
            import ar730_manager
            self.wan = ar730_manager._DemoWan()
        wan = self.wan.run(cmd, self.view)
        if wan is not None:
            return wan

        if cmd.startswith("display "):
            return self._display(cmd)
        if cmd.startswith("cut access-user"):
            if self.view != "aaa":
                return "Error: Unrecognized command found at '^' position."
            return self._cut(cmd)
        if cmd.startswith("local-user ") or cmd.startswith("undo local-user "):
            if self.view != "aaa":
                return "Error: Unrecognized command found at '^' position."
            return self._local_user(cmd)
        if cmd.startswith("user-group "):
            if self.view != "system":
                return "Error: Unrecognized command found at '^' position."
            self.groups.setdefault(cmd.split()[1], None); return ""
        return "Error: Unrecognized command found at '^' position."

    # -- local-user -----------------------------------------------------------
    def _local_user(self, cmd):
        if cmd.startswith("undo "):
            name = cmd.split()[2]
            if name not in self.users:
                return "Error: The user does not exist."
            del self.users[name]
            return ""

        parts = cmd.split()
        name = parts[1]
        rest = parts[2:]

        if rest and rest[0] == "service-type":
            u = self.users.setdefault(name, {"types": set(), "group": None, "pw": False})
            u["types"] |= set(rest[1:])
            return ""

        if rest and rest[0] == "password":
            u = self.users.get(name)
            if u is None or not u["types"]:
                # هذا ما يقوله الجهاز فعلاً عند عكس الترتيب
                return "Error: The normal service type cannot be configured."
            if rest[1] == "irreversible-cipher":
                return ("Error: The local user is not allowed to use an "
                        "irreversible encryption algorithm.")
            pw = rest[2] if len(rest) > 2 else ""
            if pw == name:
                return "Error: The password cannot be the same as a user name."
            if name in self.reject_pw_for:
                return "Error: Failed to change the password."
            u["pw"] = True
            u["pwval"] = pw
            return ""

        if rest and rest[0] == "user-group":
            u = self.users.get(name)
            if u is None:
                return "Error: The user does not exist."
            g = rest[1]
            if g not in self.groups:
                return "Error: The user group does not exist."
            u["group"] = g
            return ""

        if rest and rest[0] == "state" and len(rest) > 1:
            u = self.users.get(name)
            if u is None:
                return "Error: The user does not exist."
            u["state"] = "B" if rest[1] == "block" else "A"
            return ""

        if rest and rest[0] == "privilege":
            return ""
        return "Error: Unrecognized command found at '^' position."

    # -- cut ------------------------------------------------------------------
    def _cut(self, cmd):
        if self.view != "aaa":
            return "Error: Unrecognized command found at '^' position."
        self.cut_log.append(cmd)
        parts = cmd.split()
        key, val = parts[2], parts[3] if len(parts) > 3 else ""
        before = len(self.online)
        if key == "mac-address":
            self.online = [o for o in self.online if o["mac"] != val]
        elif key == "username":
            self.online = [o for o in self.online if o["user"] != val.split("@")[0]]
        elif key == "user-id":
            self.online = [o for o in self.online if o["id"] != val]
        if len(self.online) == before:
            return "Error: The user does not exist."
        return "Info: The users are cut successfully."

    # -- display --------------------------------------------------------------
    def _aaa_config(self):
        out = ["#", "aaa", " authentication-scheme default", " domain default",
               " domain portalusers"]
        for name in sorted(self.users):
            u = self.users[name]
            if u["pw"]:
                out.append(" local-user %s password cipher %%^%%#hidden" % name)
            if u["types"]:
                out.append(" local-user %s service-type %s" % (name, " ".join(sorted(u["types"]))))
            if u.get("priv"):
                out.append(" local-user %s privilege level %d" % (name, u["priv"]))
            if u["group"]:
                out.append(" local-user %s user-group %s" % (name, u["group"]))
        out.append("#")
        return "\n".join(out)

    def _display(self, cmd):
        if cmd.startswith("display current-configuration configuration aaa"):
            return self._aaa_config()

        if cmd.startswith("display current-configuration configuration mac-access-profile"):
            # نفس شكل الجهاز: الترويسة، والملف الفارغ بلا سطر mac-authen
            b = ["#"]
            for name in sorted(self.profiles):
                b.append("mac-access-profile name %s" % name)
                if self.profiles[name]:
                    b.append(" mac-authen username macaddress format without-hyphen "
                             "password cipher %%^%%#%08x%%^%%#"
                             % (zlib.crc32(self.profiles[name].encode()) & 0xffffffff))
            return "\n".join(b + ["#", "return"])

        if cmd.strip() == "display local-user":
            rows = ["  " + "-" * 76,
                    "  User-name                      State  AuthMask  AdminLevel",
                    "  " + "-" * 76]
            for name in sorted(self.users):
                u = self.users[name]
                rows.append("  %-30s %-6s %-9s %d" % (name, u.get("state", "A"), "X",
                                                      u.get("priv", 0)))
            rows.append("  accampus@domain_...            A      SH        15")
            rows += ["  " + "-" * 76, "  Total %d user(s)" % (len(self.users) + 1)]
            return "\n".join(rows)

        if cmd.startswith("display current-configuration"):
            blocks = ["#", "sysname AR730", "#"]
            for g in sorted(self.groups):
                blocks += ["user-group %s" % g]
                if self.groups[g]:
                    blocks += [" acl-id %s" % self.groups[g]]
                blocks += ["#"]
            blocks += ["acl number 3020", " rule 5 permit ip", "#"]
            blocks += self._aaa_config().splitlines()
            # صفحة طويلة -> ترقيم في المنتصف كما يفعل الجهاز
            text = "\n".join(blocks)
            return text

        if cmd.startswith("display user-group"):
            rows = ["  ------------------------------------------------",
                    "  Index  Group-name                       Priority",
                    "  ------------------------------------------------"]
            for i, g in enumerate(sorted(self.groups)):
                rows.append("  %-6d %-32s %d" % (i, g, 0))
            rows.append("  ------------------------------------------------")
            return "\n".join(rows)

        if cmd.startswith("display access-user"):
            rows = ["  " + "-" * 78,
                    "  UserID Username                IP address       MAC            Status",
                    "  " + "-" * 78]
            for o in self.online:
                rows.append("  %-6s %-23s %-16s %-14s %s" %
                            (o["id"], o["user"], o["ip"], o["mac"], o["status"]))
            rows.append("  " + "-" * 78)
            rows.append("  Total: %d, printed: %d" % (len(self.online), len(self.online)))
            return "\n".join(rows)

        return "Error: Unrecognized command found at '^' position."


class _Channel(object):
    """قناة تفاعلية: تصدي الأمر، تطرح [Y/N] عند save، وتضع الموجّه بعد كل رد."""

    def __init__(self, dev):
        self.dev = dev
        self.buf = b""
        self.pending_save = False
        self.closed = False
        self._line = ""
        self.pending = []           # دفعات تصل بعد توقف قصير كما يفعل الجهاز
        self.buf += ("\r\nInfo: The max number of VTY users is 8.\r\n"
                     "Warning: The initial password poses security risks.\r\n"
                     + self.dev.prompt()).encode()

    def settimeout(self, t): pass

    def send(self, data):
        for ch in data:
            if ch in ("\n", "\r"):
                self._submit(self._line)
                self._line = ""
            elif ch == " " and not self._line:
                pass                      # مسافة تغذية الترقيم
            else:
                self._line += ch
        return len(data)

    def _submit(self, line):
        cmd = line.strip()
        if self.pending_save:
            self.pending_save = False
            if cmd.upper().startswith("Y"):
                self.buf += ("Y\r\nIt will take several minutes to save configuration...\r\n"
                             "Configuration file had been saved successfully\r\n"
                             + self.dev.prompt()).encode()
            else:
                self.buf += ("N\r\n" + self.dev.prompt()).encode()
            return

        out = self.dev.run(cmd)
        if out == "__SAVE__":
            self.pending_save = True
            self.buf += ("\r\nAre you sure to continue?[Y/N]:").encode()
            return
        body = ("\r\n" + out + "\r\n") if out else "\r\n"
        if cmd.startswith("display current-configuration"):
            # الجهاز الحقيقي يرسل سطر الإصدار ثم يتوقف وهو يبني الإعداد.
            # هذا السطر بين قوسين مربعين ويشبه موجّه الأوامر.
            self.buf += b"\r\n[V300R024C00SPC100]"
            self.pending.append((body + self.dev.prompt()).encode())
            return
        self.buf += (body + self.dev.prompt()).encode()

    def recv_ready(self):
        if self.buf:
            return True
        if self.pending:
            # الدفعة التالية تصبح جاهزة، لكن هذه النظرة ترى القناة فارغة
            self.buf += self.pending.pop(0)
        return False

    def recv(self, n):
        d, self.buf = self.buf[:n], self.buf[n:]
        return d

    def close(self): self.closed = True


class SSHClient(object):
    device = None            # يُضبط من خارج الاختبار
    bad_password = "wrong"

    def __init__(self):
        self.connected = False

    def set_missing_host_key_policy(self, p): pass
    def load_system_host_keys(self): pass

    def connect(self, hostname, port=22, username=None, password=None, **kw):
        if password == self.bad_password:
            raise AuthenticationException("Authentication failed.")
        self.connected = True

    def invoke_shell(self, width=80, height=24):
        if SSHClient.device is None:
            SSHClient.device = FakeAR730()
        return _Channel(SSHClient.device)

    def close(self): self.connected = False
