import re


class DemoAnonymizer:
    """Consistently swaps real workstation names, usernames and IPs for made-up ones in text,
    e.g. to record a demo without exposing anyone. Fake names are handed out in order of first
    sight, so a given real name keeps the same fake one for the lifetime of the server."""

    FAKE_HOSTS = ["ws-atlas", "ws-boreas", "ws-castor", "ws-draco", "ws-electra", "ws-fornax", "ws-gemini",
                  "ws-hydra", "ws-izar", "ws-juno", "ws-kepler", "ws-lyra", "ws-mira", "ws-nova", "ws-orion"]
    FAKE_USERS = ["alice", "bob", "carol", "dave", "erin", "fiona", "grace", "heidi", "ivan", "judy", "kevin",
                  "laura", "mallory", "nina", "oscar", "peggy", "quinn", "rupert", "sybil", "trent", "ursula",
                  "victor", "wendy", "xavier", "yvonne", "zack", "adam", "beth", "chris", "diana", "ethan",
                  "frida", "george", "hannah", "isaac", "jasmine", "karl", "lucy", "marco", "nora", "otto",
                  "paula", "raj", "sara", "tom", "uma", "vera", "will", "yara", "zoe", "anna", "ben", "clara",
                  "dmitri", "elena", "felix", "gina", "hugo", "irene", "jonas", "kira", "leo", "maya", "nils",
                  "olga", "pietro", "rita", "sven", "tina", "ugo", "viola", "yusuf", "zara"]
    # Accounts that identify nobody, left as they are
    SYSTEM_USERS = {"root", "nobody", "gdm", "syslog", "messagebus", "lp", "man", "colord", "_apt"}

    def __init__(self):
        self._fake_by_real : dict[str, str] = {}

    def update(self, hostnames, usernames, ips):
        """Assigns fake names to any real names not seen before. Hostnames win over usernames
        for a name that is both (e.g. an account named after its workstation). Only these known
        IPs get replaced, not anything IP-shaped, which would also hit e.g. SVG path data."""
        for real in sorted(hostnames):
            self._assign(real, self.FAKE_HOSTS, "ws")
        for real in sorted(usernames):
            if real in self.SYSTEM_USERS or real.startswith(("systemd-", "#")):
                continue
            self._assign(real, self.FAKE_USERS, "user")
        for real in sorted(ips):
            if real and real not in self._fake_by_real:
                n_ips = sum(1 for r in self._fake_by_real if r.count(".") == 3 and r.replace(".", "").isdigit())
                self._fake_by_real[real] = f"10.0.0.{10 + n_ips}"

    def _assign(self, real, pool, fallback_prefix):
        if not real or real in self._fake_by_real:
            return
        taken = set(self._fake_by_real.values()) | set(self._fake_by_real)  # never reuse a real name as a fake one
        fake = next((f for f in pool if f not in taken), None)
        if fake is None:
            n = 1
            while f"{fallback_prefix}-{n}" in taken:
                n += 1
            fake = f"{fallback_prefix}-{n}"
        self._fake_by_real[real] = fake

    def unmask(self, fake):
        """The real name behind a fake one (or the input unchanged if it isn't one)."""
        return next((real for real, f in self._fake_by_real.items() if f == fake), fake)

    def anonymize(self, text):
        if not self._fake_by_real:
            return text
        names = sorted(self._fake_by_real, key=len, reverse=True)  # longest first, so "crizz" can't eat "crizzardo"
        # Whole names only: not when preceded or followed by more of a name, a word or an IP.
        # Replacements change the text's length, so space-aligned text must be built from
        # already anonymized names rather than passed through here afterwards.
        pattern = re.compile(r"(?<![\w.-])(" + "|".join(map(re.escape, names)) + r")(?![\w-]|\.\d)")
        return pattern.sub(lambda match: self._fake_by_real[match.group(1)], text)
