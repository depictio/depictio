#!/usr/bin/env python3
"""Hand-drawn schemas for the user-groups feature (PR #972).

Two diagrams, built on the shared sketch toolkit:

- ``user-groups_sharing_model`` — how a project is shared with users AND
  groups, and how the permissions chokepoint resolves the effective role
  (highest of direct and group-granted) for every enforcement site.
- ``user-groups_saml_sync`` — how SAML attributes (PR #968) provision and
  re-sync ``sso_managed`` groups plus the user profile on every login, and
  the group-governance chain (sysadmin -> P.I. -> group admins).

Generated rather than drawn so the picture can be corrected in a diff when
the flow moves; the seeded jitter makes re-runs byte-identical.

Usage::

    python dev/diagrams/user_groups.py            # writes docs/images/*.svg/.png
    python dev/diagrams/user_groups.py --no-png   # svg only (no browser render)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    GREY,
    ORANGE,
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "images" / "user-groups"


# --------------------------------------------------------------------------
# 1. Sharing model: users + groups -> Permission -> one chokepoint.
# --------------------------------------------------------------------------

SHARE_W, SHARE_H = 1560, 800


def build_sharing_model() -> Sketch:
    s = Sketch(SHARE_W, SHARE_H, seed=972)
    s.heading(
        40,
        52,
        "Group-aware project sharing",
        "a project is shared with users AND whole groups - one chokepoint resolves the effective role",
    )

    # -- principals -------------------------------------------------------
    alice = Box(40, 130, 220, 74, BLUE, "alice", ("direct owner",))
    bob = Box(40, 234, 220, 74, BLUE, "bob", ("direct viewer", "member of Lab X"))
    lab = Box(
        40,
        350,
        220,
        150,
        VIOLET,
        "Lab X  (group)",
        (
            "P.I.: carol",
            "admins: carol, dave",
            "members: carol, dave,",
            "bob, ...",
        ),
    )
    for b in (alice, bob, lab):
        s.box(b)
    s.text(150, 530, "group admins manage members,", size=13, colour=DIM)
    s.text(150, 549, "admins & metadata - no sysadmin needed", size=13, colour=DIM)

    # -- the permission block --------------------------------------------
    perm = Box(400, 130, 330, 370, WHITE, "Project . permissions", ())
    s.rect(perm)
    s.text(perm.cx, perm.y + 30, "Project . permissions", size=19, weight="bold")

    s.rect(Box(424, 180, 282, 128, BLUE, "", ()))
    s.text(565, 204, "direct (UserBase snapshots)", size=14, weight="bold")
    s.text(565, 230, "owners   [alice]", size=14, colour=DIM)
    s.text(565, 254, "editors  []", size=14, colour=DIM)
    s.text(565, 278, 'viewers  [bob]  ("*" allowed)', size=14, colour=DIM)

    s.rect(Box(424, 324, 282, 128, VIOLET, "", ()))
    s.text(565, 348, "groups ({id, name} snapshots)", size=14, weight="bold")
    s.text(565, 374, "group_owners   [Lab X]", size=14, colour=DIM)
    s.text(565, 398, "group_editors  []", size=14, colour=DIM)
    s.text(565, 422, "group_viewers  []", size=14, colour=DIM)

    s.text(perm.cx, 478, "defaults [] - pre-groups documents", size=13, colour=DIM)
    s.text(perm.cx, 496, "validate unchanged, no migration", size=13, colour=DIM)

    s.arrow(alice.right, alice.cy, 424, 226)
    s.arrow(bob.right, bob.cy, 424, 274)
    s.arrow(lab.right, lab.cy - 45, 424, 388)

    # -- the chokepoint ---------------------------------------------------
    choke = Box(
        860,
        150,
        330,
        210,
        YELLOW,
        "api/v1/permissions.py",
        (
            "build_access_query(user, level,",
            "group_ids)  -> Mongo $or",
            "resolve_effective_role(doc, ...)",
            "has_permission(doc, ...)",
            "",
            "effective role =",
            "highest(direct, via groups)",
        ),
    )
    s.box(choke)
    s.arrow(perm.right, 290, choke.x, choke.cy)

    # membership is resolved live, never denormalized
    s.line(150, 558, 150, 596, dashed=True, colour=DIM)
    s.curve([(150, 596), (860, 596), (940, 596)])
    s.arrow(940, 596, 1010, 366, dashed=True, colour=DIM)
    s.text(560, 618, "membership resolved live from the groups collection", size=14, colour=DIM)
    s.text(
        560, 638, "(1 indexed query/request - changes apply on next request,", size=13, colour=DIM
    )
    s.text(560, 656, "no token invalidation)", size=13, colour=DIM)

    # bob's worked example
    ex = Box(
        860,
        400,
        330,
        104,
        GREEN,
        "bob on this project",
        (
            "direct: viewer",
            "via Lab X (group owner): owner",
            "-> effective role: OWNER",
        ),
    )
    s.box(ex)

    # -- fan-out to the enforcement sites --------------------------------
    sites = Box(
        1290,
        150,
        230,
        354,
        ORANGE,
        "every gate",
        (
            "projects list/get",
            "dashboards (26 sites)",
            "workflows",
            "files / deltatables",
            "multiqc / advanced viz",
            "events (websocket)",
            "screenshots (Celery,",
            "own Mongo client)",
            "",
            "update_project_",
            "permissions: group",
            "admin of a group",
            "owner acts as owner",
        ),
    )
    s.box(sites)
    s.arrow(choke.right, choke.cy, sites.x, choke.cy)
    s.arrow(ex.right, ex.cy, sites.x, ex.cy)

    # -- floors and bypasses ----------------------------------------------
    s.rect(Box(400, 690, 790, 66, GREY, "", ()))
    s.text(
        795,
        718,
        'floors & bypasses: is_public / viewers "*" grant viewer to anyone .',
        size=14,
    )
    s.text(
        795,
        740,
        "sysadmins skip every filter . anonymous users see public projects only",
        size=14,
    )
    return s


# --------------------------------------------------------------------------
# 2. SAML sync + governance.
# --------------------------------------------------------------------------

SAML_W, SAML_H = 1560, 820


def build_saml_sync() -> Sketch:
    s = Sketch(SAML_W, SAML_H, seed=968)
    s.heading(
        40,
        52,
        "SSO group sync & group governance",
        "SAML attributes provision groups and profile on every login - compatible with PR #968, wired by 3 lines",
    )

    # -- login flow --------------------------------------------------------
    idp = Box(40, 140, 230, 96, BLUE, "EMBL Keycloak", ("SAML IdP", "(any IdP works)"))
    s.box(idp)

    acs = Box(400, 140, 300, 120, WHITE, "ACS callback  (PR #968)", ())
    s.rect(acs)
    s.text(acs.cx, acs.y + 27, "ACS callback  (PR #968)", size=18, weight="bold")
    s.text(acs.cx, acs.y + 54, "/auth/saml/callback", size=14, colour=DIM)
    s.text(acs.cx, acs.y + 76, "create_or_get_sso_user(email)", size=14, colour=DIM)
    s.text(acs.cx, acs.y + 98, "-> magic-link ticket -> viewer", size=14, colour=DIM)

    s.arrow(idp.right, idp.cy, acs.x, idp.cy)
    s.text(335, 132, "assertion:", size=13, colour=DIM)
    s.text(335, 150, "memberOf, title,", size=13, colour=DIM)
    s.text(335, 168, "displayName, uid", size=13, colour=DIM)

    sync = Box(
        830,
        130,
        330,
        150,
        YELLOW,
        "sync_sso_user(user, attrs)",
        (
            "auth_endpoints/sso_sync.py",
            "settings: DEPICTIO_AUTH_",
            "SAML_ATTRIBUTE_GROUPS /",
            "_TITLE / _DISPLAY_NAME / _LOGIN",
            "idempotent, runs on every login",
        ),
    )
    s.box(sync)
    s.arrow(acs.right, acs.cy, sync.x, sync.cy, dashed=True)
    s.text(765, 140, "+3 lines", size=14, colour=RED)
    s.text(765, 158, "when #968", size=13, colour=DIM)
    s.text(765, 174, "merges", size=13, colour=DIM)

    # -- what the sync touches --------------------------------------------
    sso_group = Box(
        1250,
        110,
        270,
        130,
        VIOLET,
        "Lab X  (sso_managed)",
        (
            "created if missing",
            "membership re-synced",
            "each login: adds AND",
            "removals",
        ),
    )
    s.box(sso_group)
    s.arrow(sync.right, sync.cy - 30, sso_group.x, sso_group.cy)

    manual = Box(
        1250,
        270,
        270,
        96,
        GREY,
        "manual group",
        ("created by a sysadmin", "(sso_managed=false)"),
    )
    s.box(manual)
    s.line(sync.right, sync.cy + 20, manual.x, manual.cy, colour=DIM, dashed=True)
    s.cross(1205, 272)
    s.text(1385, 394, "never touched", size=14, colour=RED)

    profile = Box(
        830,
        330,
        330,
        104,
        GREEN,
        "user profile",
        (
            "title . display_name . login",
            "sso_provider = saml",
            "shown on /profile",
        ),
    )
    s.box(profile)
    s.arrow(sync.cx, sync.bottom, profile.cx, profile.y)

    # -- governance chain --------------------------------------------------
    s.line(40, 490, 1520, 490, colour=GREY, dashed=True)
    s.text(40, 530, "who runs a group", size=22, anchor="start")

    sysadmin = Box(
        40,
        560,
        280,
        120,
        ORANGE,
        "sysadmin",
        (
            "creates / deletes groups",
            "designates the P.I.",
            "(seeded admin/users",
            "groups protected)",
        ),
    )
    pi = Box(
        420,
        560,
        280,
        120,
        PINK,
        "P.I.  (carol)",
        (
            "group admin by default",
            "can promote more",
            "group admins",
        ),
    )
    gadmin = Box(
        800,
        560,
        330,
        120,
        VIOLET,
        "group admins",
        (
            "add / remove members",
            "promote / demote admins",
            "rename, edit description",
            "manage group-owned project sharing",
        ),
    )
    surfaces = Box(
        1230,
        560,
        290,
        120,
        BLUE,
        "where",
        (
            "/groups page (self-service)",
            "Admin -> Groups tab",
            "project permissions page:",
            "Groups card",
        ),
    )
    for b in (sysadmin, pi, gadmin, surfaces):
        s.box(b)
    s.arrow(sysadmin.right, sysadmin.cy, pi.x, pi.cy)
    s.arrow(pi.right, pi.cy, gadmin.x, gadmin.cy)
    s.arrow(gadmin.right, gadmin.cy, surfaces.x, surfaces.cy)

    s.text(
        780,
        740,
        "guards: no self-demotion . a group keeps >= 1 admin (sysadmin may override) .",
        size=14,
        colour=DIM,
    )
    s.text(
        780,
        762,
        "removing a member also drops their admin role and clears P.I. if it was them",
        size=14,
        colour=DIM,
    )
    return s


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-png", action="store_true", help="skip the browser PNG render")
    args = parser.parse_args()

    write(build_sharing_model(), OUT, "sharing_model", png=not args.no_png)
    write(build_saml_sync(), OUT, "saml_sync", png=not args.no_png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
