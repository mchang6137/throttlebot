package main

import (
	"time"
	"fmt"
	"flag"
	"os"
	"path/filepath"
	"io/ioutil"

	meta_v1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	core_v1 "k8s.io/api/core/v1"
	apps_v1beta1 "k8s.io/api/apps/v1beta1"
	"k8s.io/apimachinery/pkg/api/meta"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/kubernetes"
	"k8s.io/apimachinery/pkg/watch"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/tools/clientcmd"
	// "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/client-go/informers"

	// "github.com/netsys/scotty/pkg/tools"
	// "github.com/netsys/scotty/pkg/config"
	// "github.com/sirupsen/logrus"
)

// The Informers  are responsible for watching the state of various resources
// and reporting when those resources change (add, delete, update). They enqueue
// reports as tools.Event objects for the deltacomparator to process.

// An object that has methods to build various SharedInformers.
type InformerFactory struct {
	Client		*kubernetes.Clientset
	Resync		time.Duration
	Indexers	cache.Indexers
	Queue		chan Event
}

type Metric struct {
	Query		string
	Values		map[string]float64
}

type Event struct {
	Resource	string
	Action		string
	Name		string
	Namespace	string
	Old		runtime.Object
	New		runtime.Object
	Metric		*Metric
}

type ScottyInformer interface {
	Run(stopCh <-chan struct{})
	HasSynced()	bool
}


// Creates a new InformerFactory.
func NewInformerFactory(Client *kubernetes.Clientset, wq chan Event) InformerFactory {
	return InformerFactory{
		Client: Client,
		Resync:	time.Second,
		Indexers: cache.Indexers{},
		Queue: wq,
	}
}

// Helper function to create a SharedInformer that performs tasks that are common to all Informers.
func (f InformerFactory) createGenericSharedInformer(listWatch cache.ListerWatcher, obj runtime.Object) cache.SharedIndexInformer {
	informer := cache.NewSharedIndexInformer(
		listWatch,
		obj,
		f.Resync,
		f.Indexers,
	)

	informer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc: func(obj interface{}) {
			fmt.Println("I got here")
			resource, name, namespace, err := GetResourceMetaData(obj)
			if err != nil {
				return
			}
			e := Event{
				Resource: resource,
				Action: "Add",
				Name: name,
				Namespace: namespace,
				Old: nil,
				New: obj.(runtime.Object),
			}
			f.Queue <- e

		},
		UpdateFunc: func(old, new interface{}) {
			// This is obviously wrong, but resources get updated constantly for some reason.
			// My guess is that the last liveliness probed field is constantly updated.
			// We need some updates but def not all - so I wonder if this is ok...
			resource, name, namespace, err := GetResourceMetaData(new)
			if err != nil {
				return
			}

			e := Event{
				Resource: resource,
				Action: "Update",
				Name: name,
				Namespace: namespace,
				Old: old.(runtime.Object),
				New: new.(runtime.Object),
			}

			// Update if IP has been assigned or changed.
			if resource == "pod" {
				if old.(*core_v1.Pod).Status.HostIP !=  new.(*core_v1.Pod).Status.HostIP {
					f.Queue <- e
					return
				}
			}

			// Update if generation (spec) has changed. ResourceVersion seem to be better but nodes get
			// updated all the damn time still. Should look into this.
			meta1, err := meta.Accessor(old)
			if err != nil {
				panic(fmt.Errorf("object has no meta: %v", err))
			}
			meta2, err := meta.Accessor(new)
			if err != nil {
				panic(fmt.Errorf("object has no meta: %v", err))
			}
			if meta1.GetGeneration() == meta2.GetGeneration() {
				return
			}

			f.Queue <- e
			fmt.Printf("%+v\n", e)

		},
		DeleteFunc: func(obj interface{}) {
			fmt.Println("I got here")
			resource, name, namespace, err := GetResourceMetaData(obj)
			if err != nil {
				fmt.Println(err)
			}
			e := Event{
				Resource: resource,
				Action: "Delete",
				Name: name,
				Namespace: namespace,
				Old: obj.(runtime.Object),
				New: nil,
			}
			f.Queue <- e
			event := &e
			mydata := []byte(event.Action)

			errr := ioutil.WriteFile("myfile.data", mydata, 0777)
			// handle this error
			if errr != nil {
			  // print it out
			  fmt.Println(errr)
			}
		},
	})

	return informer
}

// Creates a Shared Pod Informer.
func (f InformerFactory) CreateNewSharedPodInformer() ScottyInformer {
	// logrus.Info("INFOR: Pod Informer Created.")
	listWatch :=  &cache.ListWatch{
		ListFunc: func(options meta_v1.ListOptions) (runtime.Object, error) {
			return f.Client.CoreV1().Pods(meta_v1.NamespaceAll).List(options)
		},
		WatchFunc: func(options meta_v1.ListOptions) (watch.Interface, error) {
			return f.Client.CoreV1().Pods(meta_v1.NamespaceAll).Watch(options)
		},
	}

	return f.createGenericSharedInformer(listWatch, &core_v1.Pod{})
}

// Creates a Shared Node Informer.
func (f InformerFactory) CreateNewSharedNodeInformer() ScottyInformer {
	// logrus.Info("INFOR: Node Informer Created.")
	listWatch :=  &cache.ListWatch{
		ListFunc: func(options meta_v1.ListOptions) (runtime.Object, error) {
			return f.Client.CoreV1().Nodes().List(options)
		},
		WatchFunc: func(options meta_v1.ListOptions) (watch.Interface, error) {
			return f.Client.CoreV1().Nodes().Watch(options)
		},
	}

	return f.createGenericSharedInformer(listWatch, &core_v1.Node{})
}

// Creates a Shared Service Informer.
func (f InformerFactory) CreateNewSharedServiceInformer() ScottyInformer {
	// logrus.Info("INFOR: Service Informer Created.")
	listWatch :=  &cache.ListWatch{
		ListFunc: func(options meta_v1.ListOptions) (runtime.Object, error) {
			return f.Client.CoreV1().Services(meta_v1.NamespaceAll).List(options)
		},
		WatchFunc: func(options meta_v1.ListOptions) (watch.Interface, error) {
			return f.Client.CoreV1().Services(meta_v1.NamespaceAll).Watch(options)
		},
	}

	return f.createGenericSharedInformer(listWatch, &core_v1.Service{})
}

// Creates a Shared Deployment Informer.
func (f InformerFactory) CreateNewSharedDeploymentInformer() ScottyInformer {
	// logrus.Info("INFOR: Deployment Informer Created.")
	listWatch := &cache.ListWatch{
		ListFunc: func(options meta_v1.ListOptions) (runtime.Object, error) {
			return f.Client.AppsV1beta1().Deployments(meta_v1.NamespaceAll).List(options)
		},
		WatchFunc: func(options meta_v1.ListOptions) (watch.Interface, error) {
			return f.Client.AppsV1beta1().Deployments(meta_v1.NamespaceAll).Watch(options)
		},
	}

	return f.createGenericSharedInformer(listWatch, &apps_v1beta1.Deployment{})
}

func GetResourceMetaString(obj interface{}) (string, error) {
	resource, name, namespace, err := GetResourceMetaData(obj)
	if err != nil {
		return "", err
	}
	if namespace == "" {
		return fmt.Sprintf("%s/%s", resource, name), nil
	}
	return fmt.Sprintf("%s/%s/%s", resource, namespace, name), nil
}

func GetResourceMetaData(obj interface{}) (resource, name, namespace string, err error) {
	key, err := cache.MetaNamespaceKeyFunc(obj)
	if err != nil {
		return "", "", "", err
	}
	namespace, name, err = cache.SplitMetaNamespaceKey(key)
	if err != nil {
		return "", "", "", err
	}
	resource, err = GetResourceType(obj)
	if err != nil {
		return "", "", "", err
	}
	return resource, name, namespace, err
}

func GetResourceType(obj interface{}) (string, error) {
	switch obj.(type) {
	case *apps_v1beta1.Deployment:
		return "deployment", nil
	case *core_v1.Pod:
		return "pod", nil
	case *core_v1.Service:
		return "service", nil
	case *core_v1.Node:
		return "node", nil
	default:
		return "", fmt.Errorf("type not recoginized")
	}
}

func homeDir() string {
	if h := os.Getenv("HOME"); h != "" {
		return h
	}
	return os.Getenv("USERPROFILE") // windows
}

func getClientOutOfCluster() (*kubernetes.Clientset, error) {
	var kubeconfig *string
	if home := homeDir(); home != "" {
		kubeconfig = flag.String("kubeconfig", filepath.Join(home, ".kube", "config"), "(optional) absolute path to the kubeconfig file")
	} else {
		kubeconfig = flag.String("kubeconfig", "", "absolute path to the kubeconfig file")
	}

	config, err := clientcmd.BuildConfigFromFlags("", *kubeconfig)
	if err != nil {
		panic(err.Error())
	}

	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, err
	}

	return clientset, nil
}

func main() {
	//Configure cluster info
	// config := &amp;restclient.Config{
	// 	Host:     "https://api-throttlebot-k8s-local-aehhpj-825943492.us-east-2.elb.amazonaws.com",
	// 	Username: "admin",
	// 	Password: "YC8FeVQZdpRlL8fq2KiKRSNLh5bl17ov",
	// 	Insecure: true,
	// }
	//Create a new client to interact with cluster and freak if it doesn't work
	// kubeClient, err := client.New(config)
	// if err != nil {
	// 	log.Fatalln("Client not created sucessfully:", err)
	// }

    clientset, _:= getClientOutOfCluster()
	
	
	// wq := make(chan Event)
	// factory := NewInformerFactory(clientset, wq)

	// factory.CreateNewSharedPodInformer();

	

	//Create a cache to store Pods
	// var podsStore cache.Store
	//Watch for Pods
	// podsStore = watchPods(kubeClient, podsStore)
	//Keep alive
	// log.Fatal(http.ListenAndServe(":8080", nil))

	// for {
	// 	pods, err := clientset.CoreV1().Pods("").List(meta_v1.ListOptions{})
	// 	if err != nil {
	// 		panic(err.Error())
	// 	}
	// 	fmt.Printf("There are %d pods in the cluster\n", len(pods.Items))

		// Examples for error handling:
		// - Use helper functions like e.g. errors.IsNotFound()
		// - And/or cast to StatusError and use its properties like e.g. ErrStatus.Message
		// namespace := "default"
		// pod := "scaletest-569bfbbbbc-jwrt9"
		// _, err = clientset.CoreV1().Pods(namespace).Get(pod, meta_v1.GetOptions{})
		// if errors.IsNotFound(err) {
		// 	fmt.Printf("Pod %s in namespace %s not found\n", pod, namespace)
		// } else if statusError, isStatus := err.(*errors.StatusError); isStatus {
		// 	fmt.Printf("Error getting pod %s in namespace %s: %v\n",
		// 		pod, namespace, statusError.ErrStatus.Message)
		// } else if err != nil {
		// 	panic(err.Error())
		// } else {
		// 	fmt.Printf("Found pod %s in namespace %s\n", pod, namespace)
		// }

		// time.Sleep(10 * time.Second)
	// }



	if _, err := os.Stat(filepath.Join(homeDir(), "go", "data")); err == nil {
  		os.Remove(filepath.Join(homeDir(), "go", "data"))
  	}

	
	f, err := os.Create(filepath.Join(homeDir(), "go", "data"))


	if err != nil {
		fmt.Println(err) 
	}


	factory := informers.NewSharedInformerFactory(clientset, 0)
    informer := factory.Core().V1().Pods().Informer()
    stopper := make(chan struct{})
    defer close(stopper)
    informer.AddEventHandler(cache.ResourceEventHandlerFuncs{
        AddFunc: func(obj interface{}) {
            // "k8s.io/apimachinery/pkg/apis/meta/v1" provides an Object
            // interface that allows us to get metadata easily

            resource, name, namespace, err := GetResourceMetaData(obj)
            mObj := obj.(meta_v1.Object)
            fmt.Println("New Pod Added to Store: %s", mObj.GetName())
            fmt.Fprintln(f, "Add", name, time.Now().Unix())
            // f.flush()

            if err != nil {
            	fmt.Println(err)
            	fmt.Println(resource)
            	fmt.Println(namespace)
            }


        }, UpdateFunc: func(old, new interface{}) {
			// This is obviously wrong, but resources get updated constantly for some reason.
			// My guess is that the last liveliness probed field is constantly updated.
			// We need some updates but def not all - so I wonder if this is ok...
			
			resource, name, namespace, err := GetResourceMetaData(new)
			if err != nil {
				fmt.Println(namespace)
			}

			// e := Event{
			// 	Resource: resource,
			// 	Action: "Update",
			// 	Name: name,
			// 	Namespace: namespace,
			// 	Old: old.(runtime.Object),
			// 	New: new.(runtime.Object),
			// }

			fmt.Fprintln(f, "Update", name, time.Now().Unix())
			// f.flush()

			// Update if IP has been assigned or changed.
			if resource == "pod" {
				if old.(*core_v1.Pod).Status.HostIP !=  new.(*core_v1.Pod).Status.HostIP {
					return 
				}
			}

			// Update if generation (spec) has changed. ResourceVersion seem to be better but nodes get
			// updated all the damn time still. Should look into this.
			meta1, err := meta.Accessor(old)
			if err != nil {
				panic(fmt.Errorf("object has no meta: %v", err))
			}
			meta2, err := meta.Accessor(new)
			if err != nil {
				panic(fmt.Errorf("object has no meta: %v", err))
			}
			if meta1.GetGeneration() == meta2.GetGeneration() {
				return
			}


		}, DeleteFunc: func(obj interface{}) {
		
			resource, name, namespace, err := GetResourceMetaData(obj)

			fmt.Println("Pod Deleted From Store: %s", name)
			if err != nil {
				fmt.Println(err)
			}
			e := Event{
				Resource: resource,
				Action: "Delete",
				Name: name,
				Namespace: namespace,
				Old: obj.(runtime.Object),
				New: nil,
			}
			// f.Queue <- e
			event := &e
			fmt.Fprintln(f, event.Action, name, time.Now().Unix())
			// f.flush()
			// handle this error
			
		},
    })

	informer.Run(stopper)
}