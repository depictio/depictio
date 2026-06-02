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
import { login, fetchMe } from "../api/auth";
import { useAuthStore } from "../store/auth";

export default function AuthPage() {
  const navigate = useNavigate();
  const { setTokens, setUser } = useAuthStore();
  const [feedback, setFeedback] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  const form = useForm({
    initialValues: { email: "", password: "" },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : "Invalid email"),
      password: (v) => (v.length === 0 ? "Password is required" : null),
    },
  });

  const handleSubmit = form.onSubmit(async ({ email, password }) => {
    setSubmitting(true);
    setFeedback("");
    try {
      const tokens = await login(email, password);
      setTokens(tokens.access_token, tokens.refresh_token);
      const me = await fetchMe();
      setUser(me);
      navigate("/dashboards", { replace: true });
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Login failed. Check your credentials.";
      setFeedback(detail);
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Box id="auth-background" mih="100vh">
      <Modal
        opened
        onClose={() => {}}
        withCloseButton={false}
        id="auth-modal"
        size="md"
        centered
        title={<Title order={3}>Sign in to Depictio</Title>}
      >
        <Box id="modal-content">
          <form onSubmit={handleSubmit}>
            <Stack>
              <TextInput
                id="login-email"
                label="Email"
                placeholder="Enter your email"
                required
                {...form.getInputProps("email")}
              />
              <PasswordInput
                id="login-password"
                label="Password"
                placeholder="Enter your password"
                required
                {...form.getInputProps("password")}
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
                <Anchor id="open-register-form" size="sm" component="button">
                  Need an account? Register
                </Anchor>
              </Center>
            </Stack>
          </form>
        </Box>
      </Modal>
    </Box>
  );
}
