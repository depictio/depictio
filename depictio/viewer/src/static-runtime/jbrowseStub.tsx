/**
 * Stand-in for depictio-react-core's `JBrowseRenderer` in static bundles.
 *
 * vite.static.config.ts swaps the real module for this one. A genome browser
 * streams its tracks from the server at view time, so producers never bundle
 * one (the tile's tier is `omitted`, and its badge says why); the real
 * renderer would only add ~2.5 MB of JBrowse and its adapters to every
 * single-file bundle, which the single-file build cannot leave out because it
 * inlines every dynamic import.
 */
import React from 'react';
import { Center, Text } from '@mantine/core';

const JBrowseRenderer: React.FC<Record<string, unknown>> = () => (
  <Center h="100%" p="md">
    <Text size="sm" c="dimmed" ta="center">
      The genome browser needs a Depictio server and is not included in this static copy.
    </Text>
  </Center>
);

export default JBrowseRenderer;
