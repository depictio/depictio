import React from 'react';
import { Avatar } from '@mantine/core';

/**
 * The reader's picture filling a round avatar the Glass chrome already draws
 * (`.hy-avatar`, `.gp-avatar`): those circles carry their own size, border and
 * focus ring, so the image only has to fill them. `name` is deliberately
 * absent: if the image fails to load, Mantine falls back to its generic
 * placeholder, never to someone else's initials.
 */
export const AvatarPicture: React.FC<{ src: string }> = ({ src }) => (
  <Avatar
    src={src}
    alt=""
    radius="50%"
    style={{ width: '100%', height: '100%', minWidth: 0 }}
  />
);
