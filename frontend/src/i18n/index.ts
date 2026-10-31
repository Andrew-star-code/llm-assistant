import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/i18n/locales/en.json";
import ru from "@/i18n/locales/ru.json";

// Все строки интерфейса — только через i18n (§7.10, §20). Русский — по умолчанию.
export const resources = { ru: { translation: ru }, en: { translation: en } } as const;

void i18n.use(initReactI18next).init({
  resources,
  lng: "ru",
  fallbackLng: "ru",
  interpolation: { escapeValue: false },
  returnNull: false,
});

export default i18n;
