var dagcomponentfuncs = window.dashAgGridComponentFunctions = window.dashAgGridComponentFunctions || {};

dagcomponentfuncs.Button = function (props) {
    const {setData, data} = props;

    function onClick() {
        setData();
    }

    // Get button text from cellRendererParams (via colDef) or fall back to cell value
    const buttonValue = (props.colDef && props.colDef.cellRendererParams && props.colDef.cellRendererParams.value)
        ? props.colDef.cellRendererParams.value
        : props.value;

    return React.createElement(
        'button',
        {
            onClick: onClick,
            className: props.className,
            style: props.style || {},
        },
        buttonValue
    );
};
