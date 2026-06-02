import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Anchor,
  Box,
  Button,
  Center,
  Modal,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { login, register, fetchMe } from "../api/auth";
import { useAuthStore } from "../store/auth";

type Mode = "login" | "register";

export default function AuthPage() {
  const navigate = useNavigate();
  const { setTokens, setUser } = useAuthStore();
  const [mode, setMode] = useState<Mode>("login");
  const [feedback, setFeedback] = useState<string>("");
  const [registerFeedback, setRegisterFeedback] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  const loginForm = useForm({
    initialValues: { email: "", password: "" },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : "Invalid email"),
      password: (v) => (v.length === 0 ? "Password is required" : null),
    },
  });

  // No confirmPassword validator here: the mismatch must surface in
  // #user-feedback-message-register (handled in handleRegister), not as a
  // per-field error, to match the Cypress contract.
  const registerForm = useForm({
    initialValues: { email: "", password: "", confirmPassword: "" },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : "Invalid email"),
      password: (v) => (v.length === 0 ? "Password is required" : null),
    },
  });

  const errorDetail = (err: unknown, fallback: string): string =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data
      ?.detail ?? fallback;

  const handleLogin = loginForm.onSubmit(async ({ email, password }) => {
    setSubmitting(true);
    setFeedback("");
    try {
      const tokens = await login(email, password);
      setTokens(tokens.access_token, tokens.refresh_token);
      const me = await fetchMe();
      setUser(me);
      navigate("/dashboards", { replace: true });
    } catch (err: unknown) {
      setFeedback(errorDetail(err, "Login failed. Check your credentials."));
    } finally {
      setSubmitting(false);
    }
  });

  const handleRegister = registerForm.onSubmit(
    async ({ email, password, confirmPassword }) => {
      setRegisterFeedback("");
      if (password !== confirmPassword) {
        setRegisterFeedback("Passwords do not match.");
        return;
      }
      setSubmitting(true);
      try {
        const result = await register(email, password);
        setRegisterFeedback(
          result.success
            ? "Registration successful. You can now log in."
            : result.message || "Registration failed.",
        );
      } catch (err: unknown) {
        setRegisterFeedback(errorDetail(err, "Registration failed."));
      } finally {
        setSubmitting(false);
      }
    },
  );

  return (
    <Box id="auth-background" mih="100vh">
      <Modal
        opened
        onClose={() => {}}
        withCloseButton={false}
        id="auth-modal"
        size="md"
        centered
        title={
          <Title order={3}>
            {mode === "login" ? "Sign in to Depictio" : "Create an account"}
          </Title>
        }
      >
        <Box id="modal-content">
          {mode === "login" ? (
            <form onSubmit={handleLogin}>
              <Stack>
                <TextInput
                  id="login-email"
                  label="Email"
                  placeholder="Enter your email"
                  required
                  {...loginForm.getInputProps("email")}
                />
                <PasswordInput
                  id="login-password"
                  label="Password"
                  placeholder="Enter your password"
                  required
                  {...loginForm.getInputProps("password")}
                />
                {feedback && (
                  <Text
                    id="user-feedback-message-login"
                    c="red"
                    size="sm"
                    role="alert"
                  >
                    {feedback}
                  </Text>
                )}
                <Button
                  id="login-button"
                  type="submit"
                  loading={submitting}
                  fullWidth
                >
                  Login
                </Button>
                <Center>
                  <Anchor
                    id="open-register-form"
                    size="sm"
                    component="button"
                    type="button"
                    onClick={() => {
                      setFeedback("");
                      setMode("register");
                    }}
                  >
                    Need an account? Register
                  </Anchor>
                </Center>
              </Stack>
            </form>
          ) : (
            <form onSubmit={handleRegister}>
              <Stack>
                <TextInput
                  id="register-email"
                  label="Email"
                  placeholder="Enter your email"
                  required
                  {...registerForm.getInputProps("email")}
                />
                <PasswordInput
                  id="register-password"
                  label="Password"
                  placeholder="Choose a password"
                  required
                  {...registerForm.getInputProps("password")}
                />
                <PasswordInput
                  id="register-confirm-password"
                  label="Confirm password"
                  placeholder="Repeat your password"
                  required
                  {...registerForm.getInputProps("confirmPassword")}
                />
                {registerFeedback && (
                  <Text
                    id="user-feedback-message-register"
                    c={
                      registerFeedback.toLowerCase().includes("successful")
                        ? "green"
                        : "red"
                    }
                    size="sm"
                    role="alert"
                  >
                    {registerFeedback}
                  </Text>
                )}
                <Button
                  id="register-button"
                  type="submit"
                  loading={submitting}
                  fullWidth
                >
                  Register
                </Button>
                <Center>
                  <Anchor
                    id="open-login-form"
                    size="sm"
                    component="button"
                    type="button"
                    onClick={() => {
                      setRegisterFeedback("");
                      setMode("login");
                    }}
                  >
                    Already have an account? Login
                  </Anchor>
                </Center>
              </Stack>
            </form>
          )}
        </Box>
      </Modal>
    </Box>
  );
}
