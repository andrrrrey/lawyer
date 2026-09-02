import { Alert, Button, Form, Input } from "antd";
import { useNavigate } from "react-router-dom";

import { useLogin, useMe } from "@/api/auth";
import { ApiError } from "@/api/client";

export default function LoginPage() {
  const login = useLogin();
  const me = useMe();
  const navigate = useNavigate();

  // Уже авторизованы — сразу на дашборд.
  if (me.data) {
    navigate("/dashboard", { replace: true });
  }

  const onFinish = (values: { login: string; password: string }) => {
    login.mutate(values, {
      onSuccess: () => navigate("/dashboard", { replace: true }),
    });
  };

  const errorText =
    login.error instanceof ApiError ? login.error.message : login.error ? "Ошибка входa" : null;

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-brand">
          <div className="logo">B</div>
          <div>
            <b>Lawyer</b>
            <span>Контроль лидов и маркетинговая аналитика</span>
          </div>
        </div>

        {errorText ? (
          <Alert type="error" message={errorText} style={{ marginBottom: 16 }} showIcon />
        ) : null}

        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item
            name="login"
            label="Логин"
            rules={[{ required: true, message: "Введите логин" }]}
          >
            <Input size="large" autoFocus placeholder="admin" />
          </Form.Item>
          <Form.Item
            name="password"
            label="Пароль"
            rules={[{ required: true, message: "Введите пароль" }]}
          >
            <Input.Password size="large" placeholder="••••••••" />
          </Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            size="large"
            block
            loading={login.isPending}
          >
            Войти
          </Button>
        </Form>
      </div>
    </div>
  );
}
