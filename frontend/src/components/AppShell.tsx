/**
 * The frame around every signed-in screen: header, section links, mobile tab bar, and the
 * banners that state the condition of the data.
 *
 * Two navigations, one per hand. The Response Center is used on a laptop in a relief tent, so
 * its sections live in the header; the community product is used one-handed on a phone, so its
 * four main destinations live in a bottom bar within thumb reach. The stylesheet hides one at
 * 960px and the other below it, and the same components render on both surfaces - which is why
 * a staff account on a phone still gets a tab bar, and a community account on a desktop still
 * gets a header row.
 *
 * Items are filtered by the permission list the server sent at sign-in. That is not security -
 * every endpoint checks again - it is the difference between a link that opens a screen and a
 * link that opens a 403.
 */

import { NavLink, Outlet } from "react-router-dom";

import { homeFor, useAuth } from "../auth/AuthContext";
import { useIsNarrow } from "../hooks/useMediaQuery";
import { useI18n } from "../i18n/I18nContext";
import { RANK_KEYS } from "../i18n/strings";
import type { StringKey } from "../i18n/strings";
import { DataConditionBanner } from "./DataConditionBanner";
import { LanguageSwitch } from "./LanguageSwitch";

export interface NavItem {
  to: string;
  label: StringKey;
  /** Omitted for anything a signed-in account may always open, including its own records. */
  permission?: string;
  /** For a section index: active only on that exact path, not on every page beneath it. */
  exact?: boolean;
}

/** How many destinations fit a thumb. A fifth tab is a fifth thing to mis-tap. */
const TAB_LIMIT = 4;

export function AppShell({ items }: { items: NavItem[] }) {
  const { t, enumLabel } = useI18n();
  const { user, isStaff, can, logout } = useAuth();
  const narrow = useIsNarrow();

  const visible = items.filter((item) => can(item.permission));
  const tabs = visible.slice(0, TAB_LIMIT);
  const overflow = visible.slice(TAB_LIMIT);

  const links = (
    <>
      {visible.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.exact}>
          {t(item.label)}
        </NavLink>
      ))}
    </>
  );

  return (
    <>
      <header className="header">
        <NavLink className="brand" to={homeFor(isStaff ? "response_center" : "community")}>
          {t("app_name")}
          <small>{t(isStaff ? "surface_rc" : "surface_community")}</small>
        </NavLink>

        <nav className="nav" aria-label={t("menu")}>
          {links}
        </nav>

        <div className="row">
          <LanguageSwitch />
          {user ? (
            <>
              <span className="meta" title={t("signed_in_as", { name: user.username })}>
                {user.display_name}
                {user.rank ? ` · ${enumLabel(RANK_KEYS, user.rank)}` : ""}
              </span>
              <button type="button" className="button small ghost" onClick={logout}>
                {t("sign_out")}
              </button>
            </>
          ) : null}
        </div>
      </header>

      {/* Below the breakpoint the header nav is hidden by CSS, so the remaining sections get a
          scrollable row here rather than becoming unreachable on a phone. */}
      {narrow && overflow.length > 0 ? (
        <div className="page page-narrow">
          <nav className="nav" aria-label={t("menu")}>
            {overflow.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.exact}>
                {t(item.label)}
              </NavLink>
            ))}
          </nav>
        </div>
      ) : null}

      <main className="page stack">
        <DataConditionBanner />
        <Outlet />
      </main>

      <nav className="tabbar" aria-label={t("menu")}>
        {tabs.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.exact}>
            {t(item.label)}
          </NavLink>
        ))}
      </nav>
    </>
  );
}
