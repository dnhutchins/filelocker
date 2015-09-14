Filelocker = function(){
    var messageTabs;
    var messagePoller;
    var uploader;

    /*
    *   Description: Abstraction for handling AJAX requests.
    *   Parameters:
    *       path (string):              Service function to call (with leading slash).
    *       action (string):            String for success/error messages in form of "[update or refresh]ing [section of valuation]".
    *       payloadObject (object):     Object to be consumed by endpoint.
    *       verboseMode (bool):         Determines whether to show a success message if the request completes and there are no failure messages from the server.
    *       successFunction (function): OPTIONAL callback function to execute if the request completes.
    */
    function request(path, action, payloadObject, verboseMode, successFunction)
    {
        if (payloadObject != null) { payloadObject['requestOrigin'] = REQUEST_ORIGIN; }
        return $.ajax({
            type: "POST",
            cache: false,
            dataType: "json",
            url: FILELOCKER_ROOT + path,
            data: payloadObject,
            success: function(response) {
                if (response.fMessages.length > 0)
                    StatusResponse.show(response, action);
                else if (verboseMode)
                    StatusResponse.show(response, action);
                if (typeof (successFunction) === "function")
                    successFunction.call(this, response)
            },
            error: function(response, status, error) {
                StatusResponse.create(action, response.status + " " + status + ": " + error, false);
            }
        });
    }

    function login()
    {
        window.location.replace(FILELOCKER_ROOT);
    }
    
    function sawBanner()
    {
        Filelocker.request("/saw_banner", "reading banner", "{}", false);
    }

    function checkMessages(actionName)
    {
        Filelocker.request("/get_server_messages", actionName, "{}", false);
    }

    return {
        messageTabs:messageTabs,
        messagePoller:messagePoller,
        uploader:uploader,
        request:request,
        login:login,
        sawBanner:sawBanner,
        checkMessages:checkMessages
    };
}();
