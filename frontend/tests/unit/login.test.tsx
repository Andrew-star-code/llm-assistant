import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { json, ME, mockFetch } from "./fetchMock";
import { renderApp } from "./renderApp";

const PROVIDERS = {
  providers: ["dev", "ldap"],
  dev_users: [
    {
      login: "petrov",
      full_name: "Петров Сергей Алексеевич",
      title: "Бухгалтер",
      department: "Бухгалтерия",
    },
  ],
};

describe("Вход", () => {
  it("показывает общую ошибку при неверном пароле и шлёт CSRF-заголовок", async () => {
    document.cookie = "csrftoken=token-123; path=/";
    const calls = mockFetch({
      "GET /api/auth/me": () => json({}, 401),
      "GET /api/auth/providers": () => json(PROVIDERS),
      "POST /api/auth/login": () =>
        json({ error: { code: "invalid_credentials", message: "Неверный логин или пароль" } }, 401),
    });
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Логин"), "petrov");
    await userEvent.type(screen.getByLabelText("Пароль"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный логин или пароль");
    const login = calls.find((c) => c.method === "POST");
    expect(login?.headers.get("X-CSRF-Token")).toBe("token-123");
    expect(await login?.json()).toEqual({ login: "petrov", password: "wrong", provider: "ldap" });
  });

  it("вход провайдером dev ведёт на исходную страницу", async () => {
    let loggedIn = false;
    mockFetch({
      "GET /api/auth/me": () => (loggedIn ? json(ME) : json({}, 401)),
      "GET /api/auth/providers": () => json(PROVIDERS),
      "GET /api/auth/csrf": () => json({ csrf_token: "t" }),
      "POST /api/auth/login": () => {
        loggedIn = true;
        return json(ME);
      },
      "GET /api/profile": () =>
        json({
          ...ME,
          company: null,
          office: null,
          email: null,
          phone: null,
          mobile: null,
          manager_name: null,
          last_name: "Петров",
          address_form: "name_patronymic",
          address_form_is_default: true,
          last_login_at: null,
        }),
      "GET /ready": () => json({ status: "ready", checks: {} }),
    });
    const router = renderApp("/profile");
    await userEvent.click(await screen.findByTestId("dev-login-petrov"));
    expect(await screen.findByTestId("profile-name")).toHaveTextContent("Петров Сергей Алексеевич");
    expect(router.state.location.pathname).toBe("/profile");
  });
});
