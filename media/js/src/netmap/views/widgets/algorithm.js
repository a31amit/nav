define([
    'netmap/views/widget_mixin',
    'libs-amd/text!netmap/templates/widgets/algorithm.html',
    'libs/handlebars',
    'libs/jquery',
    'libs/underscore',
    'libs/backbone',
    'libs/backbone-eventbroker'
], function (WidgetMixin, Template) {
    var AlgorithmView = Backbone.View.extend(
        _.extend({}, WidgetMixin, {
        broker: Backbone.EventBroker,
        interests: {
            'netmap:forceRunning': 'updateStatus'
        },
        events: {
            'click .header': 'toggleWidget',
            'click input[name="freezeNodes"]': 'pauseLayoutAlgorithm'
        },
        initialize: function () {
            this.isLayoutEngineRunning = true;
            this.isContentVisible = false;
            this.broker.register(this);
            this.template = Handlebars.compile(Template);

            return this;
        },
        updateStatus: function (status) {
            this.isLayoutEngineRunning = status;
            this.render();
        },
        pauseLayoutAlgorithm: function () {
            this.broker.trigger('netmap:stopLayoutForceAlgorithm', true);
            this.isLayoutEngineRunning = false;
            this.render();
        },
        render: function () {
            this.$el.html(
                this.template({isLayoutEngineRunning: this.isLayoutEngineRunning, isWidgetVisible: this.isWidgetVisible})
            );

            return this;
        }
    }));

    return AlgorithmView;
});
