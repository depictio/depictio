import React from 'react';

import { useChromeStyle } from './chromeStyle';

/** The group a ChromeButton sits in, read by the button for its render props. */
export const ChromeGroupContext = React.createContext<string | null>(null);

export interface ChromeButtonGroupProps {
  /** What the actions have in common, e.g. `find`, `read`, `mode`. */
  group: string;
  className?: string;
  children: React.ReactNode;
}

/**
 * A run of related chrome actions. The base draws them side by side; a chrome
 * style may join them into one segmented control (`components.ButtonGroup`).
 */
export const ChromeButtonGroup: React.FC<ChromeButtonGroupProps> = ({
  group,
  className,
  children,
}) => {
  const Custom = useChromeStyle().components?.ButtonGroup;
  const cls = ['dc-action-group', className].filter(Boolean).join(' ');
  return (
    <ChromeGroupContext.Provider value={group}>
      {Custom ? (
        <Custom group={group} className={cls}>
          {children}
        </Custom>
      ) : (
        <div role="group" className={cls} data-group={group}>
          {children}
        </div>
      )}
    </ChromeGroupContext.Provider>
  );
};

export default ChromeButtonGroup;
