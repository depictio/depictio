import React from 'react';

import './server.css';

/** The "a newer release is out" dot, pinned to the corner of a trigger that
 *  is `position: relative`. Decorative: the trigger's own label says it. */
const UpdateDot: React.FC = () => <span className="dc-update-dot" aria-hidden data-testid="update-dot" />;

export default UpdateDot;
