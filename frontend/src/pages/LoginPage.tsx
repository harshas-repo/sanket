/**
 * Sign-in.
 *
 * The demo account list is fetched from `/api/auth/demo-accounts`, which creates the accounts
 * if they do not exist yet and returns the shared password - so no credential is typed from a
 * README and none is hardcoded here. When that endpoint is unavailable (it is switched off in
 * any deployment with `SANKET_ALLOW_DEMO_ACCOUNTS=false`), the section simply does not render:
 * a login screen that reports "demo accounts are disabled" to a resident looking for a way in
 * is noise about a feature they were never going to use.
 *
 * The language switch sits above the form on purpose. Someone who cannot read the language on
 * this screen has to be able to change it before doing anything else.
 */

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { homeFor, useAuth } from "../auth/AuthContext";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { useI18n } from "../i18n/I18nContext";
import { RANK_KEYS } from "../i18n/strings";
import type { DemoAccount } from "../api/types";

export function LoginPage() {
  const { t, enumLabel } = useI18n();
  const { login, busy, error } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [accounts, setAccounts] = useState<DemoAccount[] | null>(null);
  const [sharedPassword, setSharedPassword] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.auth
      .demoAccounts()
      .then((response) => {
        if (!alive) return;
        setAccounts(response.accounts);
        setSharedPassword(response.password);
      })
      .catch(() => {
        if (alive) setAccounts([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const outcome = await login(username.trim(), password);
    if (outcome.ok) navigate(homeFor(outcome.surface), { replace: true });
  }

  function useDemo(account: DemoAccount) {
    setUsername(account.username);
    // The password comes from the same response as the account list, so it is the one the
    // server is currently accepting rather than one copied from a document.
    setPassword(sharedPassword ?? "");
  }

  return (
    <div className="page page-narrow stack">
      <div className="row-between">
        <div className="brand">
          {t("app_name")}
          <small>{t("app_tagline")}</small>
        </div>
        <LanguageSwitch />
      </div>

      <div className="card stack-sm">
        <h1>{t("sign_in")}</h1>

        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="username">{t("username")}</label>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="password">{t("password")}</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          {error ? (
            <p className="notice error" role="alert">
              {t("login_failed")}: {error}
            </p>
          ) : null}

          <button
            type="submit"
            className="button primary"
            disabled={busy || !username.trim() || !password}
          >
            {busy ? t("signing_in") : t("sign_in")}
          </button>
        </form>
      </div>

      {accounts && accounts.length > 0 ? (
        <div className="card stack-sm">
          <h2>{t("demo_accounts")}</h2>
          <p className="meta">{t("demo_warning")}</p>
          {accounts.map((account) => (
            <button
              key={account.username}
              type="button"
              className="list-item"
              onClick={() => useDemo(account)}
            >
              <div className="row-between">
                <strong>{account.display_name}</strong>
                <span className="meta mono">{account.username}</span>
              </div>
              <div className="row">
                <span className="chip provenance">
                  {enumLabel(RANK_KEYS, account.rank)}
                </span>
                <span className="meta">
                  {account.surface === "response_center" ? t("surface_rc") : t("surface_community")}
                </span>
                <span className="meta">{t("use_account")}</span>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
