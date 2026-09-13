/**
 * Entry point. Every provider that wraps the whole app is here, in the order that matters:
 * language first (nothing renders without strings), then auth (routing depends on who is
 * calling), then the router.
 */
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { I18nProvider } from "./i18n/I18nContext";
import "./styles/tokens.css";
import "./styles/base.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <I18nProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </I18nProvider>
  </React.StrictMode>,
);
