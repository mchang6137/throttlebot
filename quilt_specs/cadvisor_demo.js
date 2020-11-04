var HaProxy = require("github.com/quilt/haproxy").Haproxy;
var Mongo = require("github.com/quilt/mongo");
var Node = require("github.com/quilt/nodejs");
// var mongoose = require('mongoose');
// mongoose.connect(process.env.MONGO_URI);
// AWS
var namespace = createDeployment({});
var baseMachine = new Machine({
    provider: "Amazon",
    cpu: new Range(1),
    ram: new Range(1),
    sshKeys: githubKeys("mchang6137"),
});
namespace.deploy(baseMachine.asMaster());
namespace.deploy(baseMachine.asWorker().replicate(1));
var cadvisor = new Container("google/cadvisor");
var cadvisorService = new Service("cadvisor", [cadvisor]);
var mongo = new Mongo(1);
var app = new Node({
  nWorker: 1,
  repo: "https://github.com/luise/awesome-restaurant-app.git",
  env: {
    PORT: "80",
    MONGO_URI: mongo.uri("mean-example")
  }
});
var haproxy = new HaProxy(1, app.services());
// Places all haproxy containers on separate Worker VMs.
// This is just for convenience for the example instructions, as it allows us to
// access the web application by using the IP address of any Worker VM.
haproxy.service.place(new LabelRule(true, haproxy.service));
mongo.connect(mongo.port, app);
app.connect(mongo.port, mongo);
haproxy.public();
publicInternet.connect(8080, cadvisorService);
namespace.deploy(app);
namespace.deploy(mongo);
namespace.deploy(haproxy);
namespace.deploy(cadvisorService);
