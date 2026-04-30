import React from 'react';
import { Alert, Code, Stack, Text, Button } from '@mantine/core';

interface State {
  error: Error | null;
  info: React.ErrorInfo | null;
}

/**
 * Top-level error boundary. Without one, any uncaught render error in the
 * SPA results in React unmounting silently → white page. This catches and
 * displays the error so it's debuggable.
 */
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  State
> {
  state: State = { error: null, info: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info);
    this.setState({ info });
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: '2rem', maxWidth: 900, margin: '2rem auto' }}>
          <Alert color="red" title="Viewer crashed" variant="light">
            <Stack gap="md">
              <Text size="sm">
                The React viewer hit an uncaught error during render. Check the
                browser console for the full stack trace, then send the
                "Error message" below to whoever's debugging.
              </Text>
              <div>
                <Text size="xs" fw={600} mb={4}>
                  Error message
                </Text>
                <Code block>{this.state.error.message}</Code>
              </div>
              {this.state.error.stack && (
                <div>
                  <Text size="xs" fw={600} mb={4}>
                    Stack
                  </Text>
                  <Code block style={{ fontSize: '0.7rem', maxHeight: 240, overflow: 'auto' }}>
                    {this.state.error.stack.slice(0, 2000)}
                  </Code>
                </div>
              )}
              {this.state.info?.componentStack && (
                <div>
                  <Text size="xs" fw={600} mb={4}>
                    Component stack
                  </Text>
                  <Code block style={{ fontSize: '0.7rem', maxHeight: 240, overflow: 'auto' }}>
                    {this.state.info.componentStack.slice(0, 2000)}
                  </Code>
                </div>
              )}
              <Button
                size="xs"
                variant="light"
                onClick={() => this.setState({ error: null, info: null })}
              >
                Try to recover
              </Button>
            </Stack>
          </Alert>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
