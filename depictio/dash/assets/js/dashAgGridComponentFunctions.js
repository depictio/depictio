var dagcomponentfuncs = window.dashAgGridComponentFunctions = window.dashAgGridComponentFunctions || {};

dagcomponentfuncs.Button = function (props) {
    const {setData, data} = props;

    function onClick() {
        setData();
    }
    return React.createElement(
        'button',
        {
            onClick: onClick,
            className: props.className,
            style: props.style || {},
        },
        props.value
    );
};

// SpinnerCellRenderer for loading states in AG Grid tables
dagcomponentfuncs.SpinnerCellRenderer = function (props) {
    return React.createElement(
        'div',
        {
            style: {
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                fontSize: '12px',
                color: '#666'
            }
        },
        props.value || 'Loading...'
    );
};
