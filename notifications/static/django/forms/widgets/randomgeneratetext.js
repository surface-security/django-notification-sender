// django jquery.init might have been loaded already or not...
(typeof django.jQuery !== "undefined" ? django.jQuery : $)(function() {
    django.jQuery('#id_external_token_generate').click(function() {
        var token = '';
        while (token.length < 40) {
            token += Math.random().toString(36).substring(2);
        }
        django.jQuery('#id_external_token').val(token.substring(0, 40));
        return false;
    });
});
