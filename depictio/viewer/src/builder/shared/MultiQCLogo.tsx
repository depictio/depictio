import React from 'react';
import { Box } from '@mantine/core';

/**
 * The MultiQC mark, in the variant that reads on the current page.
 *
 * The brand's dark logo (#201637) is near-invisible on a dark tile and its
 * white one on a light tile, so both are rendered and Mantine's `lightHidden` /
 * `darkHidden` show one of them. That follows the scheme through CSS alone: no
 * hook, no frame of the wrong logo while the scheme resolves.
 */
const MultiQCLogo: React.FC<{
  size: number;
  alt?: string;
  className?: string;
}> = ({ size, alt = 'MultiQC', className }) => {
  const style: React.CSSProperties = {
    width: size,
    height: size,
    objectFit: 'contain',
    flexShrink: 0,
  };
  return (
    <>
      <Box
        component="img"
        lightHidden
        src="/dashboard/logos/multiqc_icon_white.svg"
        alt={alt}
        className={className}
        style={style}
      />
      <Box
        component="img"
        darkHidden
        src="/dashboard/logos/multiqc_icon_dark.svg"
        alt={alt}
        className={className}
        style={style}
      />
    </>
  );
};

export default MultiQCLogo;
