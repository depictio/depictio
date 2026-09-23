import React from 'react';

import { useColorScheme } from '../hooks/useColorScheme';
import DepictioWordmark from './DepictioWordmark';

/**
 * The depictio wordmark, themed. The raster, its dark-mode treatment and the
 * hover easter egg live in `DepictioWordmark`.
 */
const DepictioLogo: React.FC<{ height?: number }> = ({ height = 20 }) => {
  const { colorScheme } = useColorScheme();

  return (
    <DepictioWordmark
      width="auto"
      height={height}
      alt="Depictio"
      dark={colorScheme === 'dark'}
    />
  );
};

export default DepictioLogo;
