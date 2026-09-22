import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { applyLang } from "./i18n";
import { StoreProvider } from "./store";
import "./index.css";

applyLang();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <StoreProvider>
      <App />
    </StoreProvider>
  </React.StrictMode>,
);
