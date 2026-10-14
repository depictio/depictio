import React from 'react';
import { Button, Modal, Stack, Text } from '@mantine/core';

import SignInProviders from '../../auth/components/SignInProviders';
import { useGuestSignIn } from '../../hooks/useGuestSignIn';

interface GuestSignInModalProps {
  opened: boolean;
  onClose: () => void;
}

/** What a public-mode guest gets where a signed-in user would open the
 *  comments: the way to comment is to sign in. Browsing stays open. */
const GuestSignInModal: React.FC<GuestSignInModalProps> = ({ opened, onClose }) => {
  const guest = useGuestSignIn();
  return (
    <Modal opened={opened} onClose={onClose} title="Sign in to comment" centered size="sm">
      <Stack gap="sm">
        <Text size="sm">
          You are browsing as a guest. Everything here stays open without an account; signing
          in is only needed to leave comments.
        </Text>
        <SignInProviders
          googleEnabled={guest.googleEnabled}
          samlEnabled={guest.samlEnabled}
          samlLabel={guest.samlLabel}
        />
        <Button variant="subtle" color="gray" fullWidth onClick={onClose}>
          Keep browsing
        </Button>
      </Stack>
    </Modal>
  );
};

export default GuestSignInModal;
